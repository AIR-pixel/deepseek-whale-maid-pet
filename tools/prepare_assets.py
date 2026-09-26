"""素材处理：抠图 -> 去色污染 -> 裁边 -> 降采样 -> WebP

输入 ref_assets/，输出 assets/pet/*.webp + manifest.json
"""
import json
import os
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "ref_assets")
OUT = os.path.join(ROOT, "assets", "pet")
TARGET_H = 512          # 输出统一高度
WEBP_Q = 88

MAGENTA = np.array([255.0, 0.0, 255.0])
WHITE = np.array([255.0, 255.0, 255.0])
BLACK = np.array([0.0, 0.0, 0.0])


def corner_stats(arr):
    """四角 12x12 均值，用于判断底色"""
    k = 12
    cs = [arr[:k, :k], arr[:k, -k:], arr[-k:, :k], arr[-k:, -k:]]
    return np.mean([c.reshape(-1, c.shape[-1]).mean(axis=0) for c in cs], axis=0)


def alpha_magenta(arr):
    """洋红底色 -> 软 alpha"""
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    dist = np.sqrt((r - 255.0) ** 2 + g ** 2 + (b - 255.0) ** 2)
    return np.clip((dist - 50.0) / 90.0, 0.0, 1.0).astype(np.float32)


def alpha_whitebg(arr, thr=236):
    """白底 -> 边缘连通域判定 + 软过渡"""
    near_white = (arr[..., 0] >= thr) & (arr[..., 1] >= thr) & (arr[..., 2] >= thr)
    lab, n = ndimage.label(near_white)
    if n == 0:
        return np.ones(arr.shape[:2], np.float32)
    border = np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])
    labels = np.unique(border)
    labels = labels[labels != 0]
    if labels.size == 0:
        return np.ones(arr.shape[:2], np.float32)
    bg = np.isin(lab, labels)
    # 软过渡：仅在背景 2px 邻域内按"离白的距离"渐变，避免角色内部白色被误伤
    bg_near = ndimage.binary_dilation(bg, iterations=2) & ~bg
    softness = np.clip((255.0 - arr.min(axis=2)) / 45.0, 0.0, 1.0).astype(np.float32)
    alpha = np.where(bg, 0.0, np.where(bg_near, softness, 1.0)).astype(np.float32)
    return alpha


def alpha_blackbg(arr, thr=42):
    """黑底 -> 边缘连通域判定 + 软过渡"""
    near_black = arr.max(axis=2) < thr
    lab, n = ndimage.label(near_black)
    if n == 0:
        return np.ones(arr.shape[:2], np.float32)
    border = np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])
    labels = np.unique(border)
    labels = labels[labels != 0]
    if labels.size == 0:
        return np.ones(arr.shape[:2], np.float32)
    bg = np.isin(lab, labels)
    bg_near = ndimage.binary_dilation(bg, iterations=2) & ~bg
    softness = np.clip((arr.max(axis=2) - 10.0) / 55.0, 0.0, 1.0).astype(np.float32)
    return np.where(bg, 0.0, np.where(bg_near, softness, 1.0)).astype(np.float32)


def unpremultiply(arr, alpha, bg_color):
    """obs = a*fg + (1-a)*bg  ->  fg = (obs - (1-a)*bg)/a，消除边缘底色污染"""
    a = np.clip(alpha, 1e-3, 1.0)[..., None]
    fg = (arr - (1.0 - a) * bg_color) / a
    return np.clip(fg, 0, 255)


def to_rgba(img, tag=""):
    """返回 (rgb_float_array, alpha_float_array)"""
    im = img.convert("RGBA")
    arr = np.asarray(im).astype(np.float32)
    rgb = arr[..., :3]
    a_existing = arr[..., 3] / 255.0

    k = 12
    corner_alpha = float(np.mean([
        a_existing[:k, :k].mean(), a_existing[:k, -k:].mean(),
        a_existing[-k:, :k].mean(), a_existing[-k:, -k:].mean(),
    ]))
    if corner_alpha < 0.25:
        print(f"    [{tag}] 自带透明通道 (corner_alpha={corner_alpha:.2f})")
        return rgb, a_existing

    cs = corner_stats(rgb)
    cands = {
        "洋红底": (np.linalg.norm(cs - MAGENTA), MAGENTA, alpha_magenta),
        "白底": (np.linalg.norm(cs - WHITE), WHITE, alpha_whitebg),
        "黑底": (np.linalg.norm(cs - BLACK), BLACK, alpha_blackbg),
    }
    key = min(cands, key=lambda kk: cands[kk][0])
    dist, bgc, fn = cands[key]
    print(f"    [{tag}] 判定 {key} (corner={np.round(cs,1)}, dist={dist:.0f})")
    alpha = fn(rgb)
    rgb = unpremultiply(rgb, alpha, bgc)
    return rgb, alpha


def clean_specks(alpha, min_ratio=0.006):
    """删除接触画布边缘的孤立小块（切格残留），保留角色主体与内部装饰"""
    mask = alpha > 0.5
    lab, n = ndimage.label(mask)
    if n <= 1:
        return alpha
    h, w = alpha.shape
    total = float(mask.sum())
    border = np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])
    border_labels = set(np.unique(border).tolist())
    border_labels.discard(0)
    areas = ndimage.sum(mask, lab, index=np.arange(1, n + 1))
    biggest = int(np.argmax(areas)) + 1
    drop = [i for i in range(1, n + 1)
            if i != biggest and i in border_labels and areas[i - 1] < total * min_ratio]
    if drop:
        alpha = alpha.copy()
        alpha[np.isin(lab, drop)] = 0.0
        print(f"    [{len(drop)} 处边缘残留已清理]")
    return alpha


def autotrim(rgb, alpha, pad=6):
    """按 alpha 裁掉透明边"""
    ys, xs = np.where(alpha > 0.06)
    if ys.size == 0:
        return rgb, alpha
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + 1 + pad, alpha.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + 1 + pad, alpha.shape[1])
    return rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]


def bbox_ratio(alpha, pad=6):
    """返回裁剪框占画布的比例 (y0,y1,x0,x1)"""
    ys, xs = np.where(alpha > 0.06)
    h, w = alpha.shape
    if ys.size == 0:
        return (0.0, 1.0, 0.0, 1.0)
    return (max(ys.min() - pad, 0) / h, min(ys.max() + 1 + pad, h) / h,
            max(xs.min() - pad, 0) / w, min(xs.max() + 1 + pad, w) / w)


def crop_by_ratio(rgb, alpha, r):
    h, w = alpha.shape
    y0, y1 = round(r[0] * h), round(r[1] * h)
    x0, x1 = round(r[2] * w), round(r[3] * w)
    return rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]


def compose(rgb, alpha):
    out = np.dstack([rgb, alpha * 255.0]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def finalize(name, img, records, ratio=None, ratio_out=None):
    rgb, alpha = to_rgba(img, name)
    if ratio is not None:
        rgb, alpha = crop_by_ratio(rgb, alpha, ratio)
    else:
        alpha = clean_specks(alpha)
        if ratio_out is not None:
            ratio_out.update({"bbox": bbox_ratio(alpha)})
        rgb, alpha = autotrim(rgb, alpha)
    pil = compose(rgb, alpha)
    w, h = pil.size
    nh = TARGET_H
    nw = max(1, round(w * nh / h))
    pil = pil.resize((nw, nh), Image.LANCZOS)
    path = os.path.join(OUT, name + ".webp")
    pil.save(path, "WEBP", quality=WEBP_Q, alpha_quality=95, method=6)
    size = os.path.getsize(path)
    records.append({"name": name, "w": nw, "h": nh, "bytes": size})
    print(f"  {name:16s} {nw:4d}x{nh:<4d}  {size/1024:6.1f} KB")
    return pil


def split_grid(img, cols, inset_x=14, inset_y=3):
    """等分切格，并向内缩边以避开格间分隔线"""
    w, h = img.size
    step = w / cols
    out = []
    for i in range(cols):
        x0 = round(i * step) + inset_x
        x1 = round((i + 1) * step) - inset_x
        out.append(img.crop((x0, inset_y, x1, h - inset_y)))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    records = []

    print("[单图]")
    blink_ref = {}
    finalize("idle_open", Image.open(os.path.join(REF, "deepseek-idle.png")), records,
             ratio_out=blink_ref)
    finalize("idle_blink", Image.open(os.path.join(REF, "frames", "idle-blink.png")), records,
             ratio=blink_ref.get("bbox"))
    finalize("work_keypress", Image.open(os.path.join(REF, "frames", "thinking-keypress.png")), records)
    finalize("work_desk", Image.open(os.path.join(REF, "frames", "desk-coding-hands-up.png")), records)

    print("[待机反应 4 格]")
    grid = Image.open(os.path.join(REF, "deepseek-idle-reactions-source.png"))
    for name, cell in zip(["eat", "doze", "sleep", "whale"], split_grid(grid, 4)):
        finalize(name, cell, records)

    print("[语义反应 2 格]")
    grid = Image.open(os.path.join(REF, "deepseek-semantic-reactions-source.png"))
    for name, cell in zip(["blindfold", "happy"], split_grid(grid, 2)):
        finalize(name, cell, records)

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    total = sum(r["bytes"] for r in records)
    print(f"\n共 {len(records)} 张，合计 {total/1024:.1f} KB -> {OUT}")


if __name__ == "__main__":
    main()
