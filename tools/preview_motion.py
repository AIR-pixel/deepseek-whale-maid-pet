# -*- coding: utf-8 -*-
"""动效预览：生成

1. preview_motion.png  —— 8 个状态 x 8 帧的位姿对比图（静态，看幅度）
2. preview_motion.gif  —— 4 个状态并排的循环动画（动态，看节奏）

无头运行，不需要真实屏幕。用法: python tools/preview_motion.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
from PIL import Image  # noqa: E402

import deepseek_pet as dp  # noqa: E402
import motion  # noqa: E402

# 预览用临时配置，绝不写用户的 config.json
dp.CONFIG_PATH = os.path.join(tempfile.gettempdir(), "deepseek_pet_preview_cfg.json")

STATES = [
    ("idle_open", "待机 · 呼吸"),
    ("work_keypress", "工作 · 打字"),
    ("eat", "干饭 · 咀嚼"),
    ("doze", "犯困 · 点头"),
    ("sleep", "睡觉 · 深呼吸"),
    ("whale", "鲸鱼 · 漂浮"),
    ("blindfold", "蒙眼 · 发抖"),
    ("happy", "开心 · 蹦跳"),
]
GIF_STATES = [("idle_open", "待机"), ("doze", "犯困"), ("whale", "鲸鱼"), ("happy", "开心")]

PREVIEW_H = 150      # 预览用角色高度
NF = 8               # 静态图每状态采样帧数


def qimage_to_pil(qimg):
    from PIL import Image
    img = qimg.convertToFormat(QImage.Format_RGB888)
    ptr = img.bits()
    ptr.setsize(img.byteCount())
    return Image.frombuffer("RGB", (img.width(), img.height()),
                            bytes(ptr), "raw", "RGB", img.bytesPerLine(), 1)


# 无头 offscreen 平台**没有字体库**（QFontDatabase().families() == 0），
# 用 QPainter.drawText 会静默不画任何东西。所有文字一律交给 PIL 渲染。
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\segoeui.ttf",
)


def pil_font(size):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    print("  ! 找不到可用字体，标签将退化为默认位图字体")
    return ImageFont.load_default()


def label_text(img, text, xy, size=13, fill=(38, 46, 68)):
    from PIL import ImageDraw
    ImageDraw.Draw(img).text(xy, text, fill=fill, font=pil_font(size))


def render_motion_sheet(pet, out):
    LABEL_W = 132
    cw, ch = pet.win_w, pet.win_h
    W, H = LABEL_W + NF * cw, len(STATES) * ch
    sheet = QImage(W, H, QImage.Format_RGB32)
    sheet.fill(QColor(248, 250, 253))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setPen(QColor(224, 230, 240))
    for c in range(NF + 1):
        p.drawLine(LABEL_W + c * cw, 0, LABEL_W + c * cw, H)
    for r in range(len(STATES) + 1):
        p.drawLine(0, r * ch, W, r * ch)

    for r, (name, label) in enumerate(STATES):
        cyc = motion.cycle(name)
        pet._cur = name
        pet._state_t0 = 0.0
        for c in range(NF):
            pet._t = cyc * c / NF
            pet.repaint()
            p.drawPixmap(LABEL_W + c * cw, r * ch, pet.grab())
    p.end()

    target_w = 1560
    k = target_w / W
    img = qimage_to_pil(sheet).resize((target_w, round(H * k)), Image.LANCZOS)
    rch = round(ch * k)
    for r, (name, label) in enumerate(STATES):
        label_text(img, label, (9, r * rch + rch // 2 - 9))
    img.save(out)
    print(f"  {os.path.basename(out)}  {img.width}x{img.height}")


def render_gif(pet, out, dur=3.6, fps=10, target_w=780):
    names = [n for n, _ in GIF_STATES]
    cw, ch = pet.win_w, pet.win_h
    W, H = cw * len(names), ch
    nf = int(round(dur * fps))
    frames = []
    for i in range(nf):
        t = dur * i / nf
        canvas = QImage(W, H, QImage.Format_RGB32)
        canvas.fill(QColor(243, 246, 252))
        p = QPainter(canvas)
        for k, name in enumerate(names):
            pet._cur = name
            pet._state_t0 = 0.0
            pet._t = t
            pet.repaint()
            p.drawImage(k * cw, 0, pet.grab().toImage())
        # 分隔线
        p.setPen(QColor(219, 226, 238))
        for k in range(1, len(names)):
            p.drawLine(k * cw, 0, k * cw, H)
        p.end()
        frames.append(qimage_to_pil(canvas))
    from PIL import Image
    s = target_w / frames[0].width
    frames = [f.resize((target_w, round(f.height * s)), Image.LANCZOS) for f in frames]
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, optimize=True, disposal=2)
    print(f"  {os.path.basename(out)}  {frames[0].width}x{frames[0].height}  "
          f"{nf} 帧 / {dur}s  {os.path.getsize(out)/1024:.0f} KB")


def render_size_ladder(pet, out, heights=(80, 100, 130, 190, 280, 380, 460, 560)):
    """把同一个状态在不同高度下并排画出来，看清"最小到底有多小"。

    窗口尺寸是按最大帧（横躺的鲸鱼）定的，直接 grab 会有大片留白，
    所以按立绘的实际落点裁紧再拼。
    """
    GAP, MARGIN = 20, 6
    shots = []
    for h in heights:
        pet._set_height(h)
        pet._cur = "idle_open"
        pet._state_t0 = 0.0
        pet._t = 0.9                      # 取呼吸中段，姿态稳定
        pet.repaint()
        img = pet.grab().toImage()
        x, y = pet._frame_pos("idle_open")
        w, hh = pet.lsize["idle_open"]
        img = img.copy(max(0, x - MARGIN), max(0, y - MARGIN),
                       w + MARGIN * 2, hh + MARGIN * 2)
        shots.append((h, img))

    W = 20 + sum(im.width() for _, im in shots) + GAP * len(shots)
    H = max(im.height() for _, im in shots) + 62
    sheet = QImage(W, H, QImage.Format_RGB32)
    sheet.fill(QColor(248, 250, 253))

    base = H - 30                          # 脚底对齐线
    xs = []
    p = QPainter(sheet)
    x = 12
    for h, im in shots:
        p.drawImage(x, base - im.height(), im)
        xs.append(x)
        p.setPen(QColor(210, 218, 230))
        p.drawLine(x + im.width() + GAP // 2, 34,
                   x + im.width() + GAP // 2, base)
        x += im.width() + GAP
    p.setPen(QColor(176, 186, 202))
    p.drawLine(0, base, W, base)
    p.end()

    img = qimage_to_pil(sheet)
    label_text(img, "尺寸阶梯（脚底对齐，数值为角色高度）", (12, 14))
    for (h, _), x in zip(shots, xs):
        label_text(img, f"{h}px", (x, base + 8), size=12)
    img.save(out)
    print(f"  {os.path.basename(out)}  {img.width}x{img.height}")


def main():
    app = QApplication([])
    cfg = dp.load_cfg()
    cfg["height"] = PREVIEW_H
    pet = dp.PetWindow(cfg)
    pet.show()
    print(f"预览窗口 {pet.win_w}x{pet.win_h}（角色 {PREVIEW_H}px，动效余量 {pet.motion_pad}px）")
    render_motion_sheet(pet, os.path.join(ROOT, "preview_motion.png"))
    render_gif(pet, os.path.join(ROOT, "preview_motion.gif"))
    render_size_ladder(pet, os.path.join(ROOT, "preview_size.png"))


if __name__ == "__main__":
    main()
