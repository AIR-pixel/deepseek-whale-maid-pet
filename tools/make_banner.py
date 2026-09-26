# -*- coding: utf-8 -*-
r"""生成 README 头图 docs/banner.png（1400x420）。

用真实立绘 `assets/pet/idle_open.webp` 合成，不画假的界面截图。
渐变底 + 角色右侧站立 + 左侧文案，深色底在 GitHub 亮/暗两种主题下都成立。

用法: python tools/make_banner.py
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "assets", "pet", "idle_open.webp")
OUT = os.path.join(ROOT, "docs", "banner.png")

W, H = 1400, 420
# 底色两端：深海军蓝 -> DeepSeek 系蓝紫
C_TL, C_BR = (13, 21, 43), (77, 107, 254)
# 角色底部留白：立绘要"站在"底边上，留一点地面感
BASELINE = 18
PET_H = 352

FONT_DIR = r"C:\Windows\Fonts"
BOLD = ("msyhbd.ttc", "msyh.ttc", "simhei.ttf")
REG = ("msyh.ttc", "simhei.ttf", "segoeui.ttf")


def font(cands, size):
    for name in cands:
        p = os.path.join(FONT_DIR, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise RuntimeError("找不到可用字体: " + repr(cands))


def gradient(w, h, c1, c2):
    """对角线性渐变。比 PIL 的 linear_gradient 好控方向。"""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    t = (x / max(w - 1, 1) * 0.72 + y / max(h - 1, 1) * 0.28)
    t = np.clip(t, 0.0, 1.0)[..., None]
    a = np.array(c1, np.float32)[None, None, :]
    b = np.array(c2, np.float32)[None, None, :]
    return Image.fromarray((a + (b - a) * t).astype(np.uint8), "RGB")


def main():
    img = gradient(W, H, C_TL, C_BR).convert("RGBA")

    # 角色后方一团柔光，让立绘从背景里"浮"出来
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([980, 40, 1400, 460], fill=(150, 185, 255, 58))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(95)))

    # 立绘：等比缩放到 PET_H，底部对齐
    pet = Image.open(SRC).convert("RGBA")
    pw = round(pet.width * PET_H / pet.height)
    pet = pet.resize((pw, PET_H), Image.LANCZOS)
    px, py = 1040, H - BASELINE - PET_H
    # 一点点落地阴影，不然像贴在纸上
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([px + pw * 0.14, py + PET_H - 16,
                               px + pw * 0.86, py + PET_H + 18],
                              fill=(6, 12, 34, 130))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(pet, (px, py))

    d = ImageDraw.Draw(img)
    f_eyebrow = font(REG, 21)
    f_title = font(BOLD, 62)
    f_sub = font(REG, 25)
    f_chip = font(REG, 20)

    x = 74
    d.text((x, 92), "非官方同人作品 · FAN-MADE", font=f_eyebrow, fill=(168, 190, 255))

    title = "DeepSeek 鲸鱼娘"
    d.text((x, 128), title, font=f_title, fill=(255, 255, 255))
    tw = d.textlength(title, font=f_title)
    d.text((x + tw + 16, 128), "桌面宠物", font=f_title, fill=(178, 200, 255))

    d.text((x, 222), "轻量 · 纯本地 · 无联网 · 无后台服务", font=f_sub,
           fill=(206, 219, 255))

    # 三个卖点小标签。
    # 注意：不要用"浅色字 + 半透明白底"——在亮渐变上会糊成一片看不出字（踩过）。
    # 深底 + 高对比亮字才是稳的。
    chips = ["10 套独立动效", "15 条合成音效", "22 MB 免安装包"]
    cx, cy = x, 286
    for c in chips:
        w = d.textlength(c, font=f_chip)
        d.rounded_rectangle([cx, cy, cx + w + 34, cy + 42], radius=21,
                            fill=(9, 18, 45, 150), outline=(150, 185, 255, 130),
                            width=1)
        d.text((cx + 17, cy + 9), c, font=f_chip, fill=(235, 242, 255))
        cx += w + 34 + 14

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.convert("RGB").save(OUT, "PNG", optimize=True)
    print(f"  {os.path.relpath(OUT, ROOT)}  {img.width}x{img.height}  "
          f"({os.path.getsize(OUT) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
