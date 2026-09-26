# -*- coding: utf-8 -*-
"""把 assets/sfx 下的音效画成一张波形总览图。

用处：音效没法"看"，但波形能一眼看出三件事——
  每条多长（横轴按同一时间尺度，长度可比）、
  起音快不快 / 衰减干不干净（有没有拖尾、有没有直流爆音）、
  峰值配平是否合理（别有的几乎贴顶、有的细如发丝）。

不依赖 Qt，纯 PIL 绘制（无头平台没有字体库，QPainter 画不出字）。
用法: python tools/preview_sfx.py
"""
import os
import wave

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SFX_DIR = os.path.join(ROOT, "assets", "sfx")
OUT = os.path.join(ROOT, "preview_sfx.png")

W = 1500                 # 总宽
LABEL_W = 132            # 左侧文字区
ROW_H = 46
PAD_TOP = 54
PAD_BOTTOM = 26
SPAN = 0.62              # 时间轴覆盖 0 ~ 0.62s（最长的一条 574ms）

BG = (248, 250, 253)
GRID = (226, 232, 242)
AXIS = (198, 208, 222)
WAVE = (46, 92, 176)
WAVE2 = (120, 170, 220)
TEXT = (38, 46, 68)
DIM = (128, 140, 162)

_FONTS = (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
          r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\segoeui.ttf")


def font(size):
    from PIL import ImageFont
    for p in _FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def read_wav(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    y = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    return y, sr


def envelope(y, sr, width):
    """把样本压成 width 列，每列取 min/max，画波形用。"""
    if len(y) == 0:
        return np.zeros(width), np.zeros(width)
    idx = np.linspace(0, len(y), width + 1).astype(int)
    lo = np.empty(width)
    hi = np.empty(width)
    for i in range(width):
        seg = y[idx[i]:max(idx[i] + 1, idx[i + 1])]
        lo[i], hi[i] = (seg.min(), seg.max()) if len(seg) else (0.0, 0.0)
    return lo, hi


def main():
    files = sorted(f for f in os.listdir(SFX_DIR) if f.endswith(".wav"))
    if not files:
        raise SystemExit("assets/sfx 下没有 wav")

    wave_x0 = LABEL_W
    wave_x1 = W - 40
    wave_w = wave_x1 - wave_x0

    H = PAD_TOP + ROW_H * len(files) + PAD_BOTTOM
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_label = font(13)
    f_small = font(11)
    f_title = font(14)

    d.text((20, 18), "交互音效总览", fill=TEXT, font=f_title)
    d.text((130, 20), f"{len(files)} 条 · 横轴同一时间尺度 · 纵轴为振幅",
           fill=DIM, font=f_small)

    # 时间刻度
    for ms in range(0, int(SPAN * 1000) + 1, 100):
        x = wave_x0 + wave_w * (ms / 1000.0) / SPAN
        if x > wave_x1:
            break
        major = (ms % 200 == 0)
        d.line([(x, PAD_TOP - 12), (x, H - PAD_BOTTOM + 4)],
               fill=GRID if not major else AXIS, width=1)
        if major:
            d.text((x + 3, PAD_TOP - 26), f"{ms}ms", fill=DIM, font=f_small)

    total = 0
    for i, fn in enumerate(files):
        name = os.path.splitext(fn)[0]
        path = os.path.join(SFX_DIR, fn)
        total += os.path.getsize(path)
        y, sr = read_wav(path)
        dur = len(y) / sr
        cy = PAD_TOP + i * ROW_H + ROW_H // 2

        # 行底色：隔行做极浅的分带，方便对行
        if i % 2 == 0:
            d.rectangle([0, PAD_TOP + i * ROW_H, W, PAD_TOP + (i + 1) * ROW_H],
                        fill=(252, 253, 255))
        d.line([(wave_x0, cy), (wave_x1, cy)], fill=AXIS, width=1)

        cols = max(1, int(wave_w * min(dur, SPAN) / SPAN))
        lo, hi = envelope(y, sr, cols)
        peak = float(max(np.abs(lo).max(), np.abs(hi).max()))
        half = ROW_H // 2 - 6
        for c in range(cols):
            x = wave_x0 + c
            a = cy - hi[c] * half
            b = cy - lo[c] * half
            d.line([(x, a), (x, max(b, a + 1))], fill=WAVE)
        d.line([(wave_x0 + cols, cy), (wave_x1, cy)], fill=WAVE2, width=1)

        d.text((16, cy - 8), name, fill=TEXT, font=f_label)
        d.text((16, cy + 6), f"{dur * 1000:.0f}ms  {os.path.getsize(path) / 1024:.1f}K  pk{peak:.2f}",
               fill=DIM, font=f_small)

    d.line([(wave_x0, H - PAD_BOTTOM + 4), (wave_x1, H - PAD_BOTTOM + 4)],
           fill=AXIS, width=1)
    d.text((16, H - PAD_BOTTOM + 8), f"合计 {total / 1024:.0f} KB", fill=TEXT, font=f_small)

    img.save(OUT)
    print(f"  preview_sfx.png  {img.width}x{img.height}  ({len(files)} 条 / {total / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
