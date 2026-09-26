# -*- coding: utf-8 -*-
"""程序合成桌宠的交互音效（清亮电子音 · 可爱 · 简短）。

为什么不用现成音效素材：
  1. 版权干净——全部由正弦/三角波 + 包络算出，没有任何采样来源；
  2. 体积极小——整包 WAV 约 100 KB，符合"轻量化"要求；
  3. 可调——风格不对改几个数字重跑即可，不用重新找素材。

输出: assets/sfx/*.wav  (16-bit 单声道 22050Hz，QSoundEffect 可直接播放)
用法: python tools/make_sfx.py
"""
import os
import wave

import numpy as np

SR = 22050
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "assets", "sfx")

# 音名 -> 频率，写音效时直接引用，比裸数字可读
N = {
    "C5": 523.25, "E5": 659.26, "G5": 783.99, "A5": 880.0, "B5": 987.77,
    "C6": 1046.50, "D6": 1174.66, "E6": 1318.51, "F6": 1396.91, "G6": 1568.00,
    "A6": 1760.00, "B6": 1975.53, "C7": 2093.00, "E7": 2637.02, "G7": 3136.00,
}

RNG = np.random.default_rng(20260926)     # 固定种子：每次生成的噪声一致，便于复现


def n_of(dur):
    return max(1, int(round(SR * dur)))


# ------------------------------------------------------------------ 基本元件

def env(dur, attack=0.003, curve=4.0, tail=0.004):
    """快起 + 指数衰减。末尾线性收尾，否则截断处会有"啪"的直流爆音。"""
    n = n_of(dur)
    a = min(n, max(1, n_of(attack)))
    e = np.ones(n)
    e[:a] = np.linspace(0.0, 1.0, a)
    rest = n - a
    if rest > 0:
        e[a:] = np.exp(-curve * np.linspace(0.0, 1.0, rest))
    f = min(n, max(1, n_of(tail)))
    e[-f:] *= np.linspace(1.0, 0.0, f)
    return e


def osc(dur, f0, f1=None, kind="tri"):
    """单振荡器；给 f1 就做滑音（对数插值，听感上是均匀的音高变化）。"""
    n = n_of(dur)
    t = np.arange(n) / SR
    if f1 is None or abs(f1 - f0) < 1e-9:
        f = np.full(n, float(f0))
    else:
        f = f0 * (f1 / f0) ** (t / dur)
    ph = 2.0 * np.pi * np.cumsum(f) / SR
    if kind == "sq":
        return np.sign(np.sin(ph))
    if kind == "saw":
        return 2.0 * ((ph / (2.0 * np.pi)) % 1.0) - 1.0
    if kind == "tri":                     # 三角波：比方波柔和，比正弦有"电子味"
        return 2.0 / np.pi * np.arcsin(np.sin(ph))
    return np.sin(ph)


def chime(dur, f0, f1=None, harm=(1.0, 0.30, 0.12), detune=1.004,
          attack=0.003, curve=4.0):
    """"清亮电子音"的主体：三角波叠加泛音，再叠一层微失谐的同族波做闪光感。"""
    y = np.zeros(n_of(dur))
    ratio = (f1 / f0) if f1 else None
    for i, h in enumerate(harm, start=1):
        y += h * osc(dur, f0 * i, (f0 * i * ratio) if ratio else None, "tri")
    if detune and detune != 1.0:
        for i, h in enumerate(harm, start=1):
            f = f0 * i * detune
            y += h * 0.5 * osc(dur, f, (f * ratio) if ratio else None, "tri")
    m = np.max(np.abs(y))
    if m > 0:
        y /= m
    return y * env(dur, attack, curve)


def noise(dur, lp=0.25, curve=6.0, attack=0.001):
    """低通噪声。用于"啵""咔哒"这类需要瞬态颗粒感的地方。"""
    n = n_of(dur)
    x = RNG.uniform(-1.0, 1.0, n)
    k = max(2, int(1.0 / max(lp, 1e-3)))
    ker = np.exp(-np.arange(k) / (k * 0.35))
    ker /= ker.sum()
    x = np.convolve(x, ker, mode="same")
    m = np.max(np.abs(x))
    if m > 0:
        x /= m
    return x * env(dur, attack, curve)


def mix(*parts):
    """把若干 (起始秒, 波形) 叠加成一条。"""
    total = max(int(round(s * SR)) + len(a) for s, a in parts)
    out = np.zeros(total)
    for s, a in parts:
        i = int(round(s * SR))
        out[i:i + len(a)] += a
    return out


# ------------------------------------------------------------------ 音效清单
# 每个 cue 对应一个明确的交互时机，命名与 deepseek_pet.py 里的调用点一致。

def c_hello():
    """启动问候：上行四音 + 尾音闪光，像开机音但不吵。"""
    ns = ["C6", "E6", "G6", "C7"]
    parts = []
    for i, nm in enumerate(ns):
        d = 0.24 if i == len(ns) - 1 else 0.10
        parts.append((i * 0.078, chime(d, N[nm], curve=4.5)))
    parts.append((0.234, chime(0.34, N["G7"] * 0.5, N["G7"], harm=(1.0, 0.2), detune=0.0)))
    return mix(*parts)


def c_click():
    """单击 / 菜单：单个上滑短音，最短最亮的一条。"""
    return chime(0.072, 1360.0, 2080.0, curve=5.5)


def c_pop():
    """气泡弹出：极短的"啵"，带一点噪声颗粒。"""
    return mix((0.0, noise(0.022, lp=0.5)),
               (0.0, chime(0.042, 1750.0, 2350.0, curve=7.0) * 0.7))


def c_hop():
    """双击蹦跳：E6 -> B6 上行两音，第二音稍长，收在最高处。"""
    return mix((0.0, chime(0.075, N["E6"], N["G6"], curve=5.0)),
               (0.072, chime(0.155, N["B6"], N["C7"], curve=4.0)))


def c_happy():
    """开心：大三和弦琶音上行 + 高音闪光，最"明亮"的一条。"""
    return mix((0.000, chime(0.10, N["C6"], curve=4.5)),
               (0.076, chime(0.10, N["E6"], curve=4.5)),
               (0.152, chime(0.10, N["G6"], curve=4.5)),
               (0.228, chime(0.26, N["C7"], curve=3.2)),
               (0.300, chime(0.20, N["E7"], N["G7"], harm=(1.0, 0.18), detune=0.0) * 0.5))


def c_shy():
    """害羞：下滑小两度 + 轻颤音，音色软下来。"""
    y = chime(0.30, N["G6"], N["E6"], curve=3.0, attack=0.006)
    n = len(y)
    vib = 1.0 + 0.004 * np.sin(2.0 * np.pi * 11.0 * np.arange(n) / SR)
    return y * vib


def c_whale():
    """变回鲸鱼原型：正弦下潜 + 气泡感噪声，一下沉到水里。"""
    return mix((0.0, osc(0.34, 720.0, 270.0, "sine") * env(0.34, 0.006, 2.6)),
               (0.16, noise(0.20, lp=0.10, curve=5.0) * 0.55))


def c_eat():
    """干饭：两下短促的"咀嚼"，噪声瞬态 + 低音，听着才有颗粒。"""
    return mix((0.0, noise(0.030, lp=0.45) * 0.8),
               (0.0, chime(0.070, N["E5"], curve=6.0) * 0.55),
               (0.115, noise(0.028, lp=0.45) * 0.7),
               (0.115, chime(0.062, N["G5"], curve=6.0) * 0.5))


def c_grab():
    """拖拽拿起：短上滑。"""
    return chime(0.062, 940.0, 1480.0, curve=5.5)


def c_drop():
    """拖拽放下：短下滑，比拿起柔一点。"""
    return chime(0.092, 1520.0, 900.0, curve=4.0, attack=0.005)


def c_zoom_up():
    """滚轮放大：极高的短促上滑，音量刻意压低。"""
    return chime(0.042, 1850.0, 2400.0, curve=7.0, harm=(1.0, 0.22)) * 0.62


def c_zoom_down():
    """滚轮缩小：同族下滑。"""
    return chime(0.042, 2400.0, 1850.0, curve=7.0, harm=(1.0, 0.22)) * 0.62


def c_wake():
    """从犯困 / 睡眠被叫醒：上行两音，明快。"""
    return mix((0.0, chime(0.10, N["A5"], N["C6"], curve=4.5)),
               (0.082, chime(0.18, N["E6"], N["G6"], curve=3.5)))


def c_work():
    """开始干活：两下轻"咔哒"，模拟键帽。"""
    return mix((0.0, noise(0.020, lp=0.55, curve=9.0) * 0.75),
               (0.012, chime(0.045, 900.0, 760.0, curve=8.0, harm=(1.0, 0.15)) * 0.5),
               (0.062, noise(0.018, lp=0.55, curve=9.0) * 0.62),
               (0.072, chime(0.040, 1020.0, 860.0, curve=8.0, harm=(1.0, 0.15)) * 0.42))


def c_remind():
    """定时提醒（喝水 / 久坐）：两下"叮咚"。提醒音的意义就是被听见，
    所以它是这组里最"正式"的一条——比交互音长、比交互音亮。"""
    return mix((0.000, chime(0.20, N["E6"], curve=3.2)),
               (0.170, chime(0.40, N["A6"], curve=2.4)),
               (0.170, chime(0.40, N["C7"], curve=2.4, harm=(1.0, 0.22)) * 0.5))


# 名称 -> (生成函数, 目标峰值)。峰值按"该有多显眼"配，不一律拉满，
# 否则滚轮音这种高频小音会比启动音还刺耳。
CUES = {
    "hello":     (c_hello,     0.86),
    "click":     (c_click,     0.60),
    "pop":       (c_pop,       0.40),
    "hop":       (c_hop,       0.80),
    "happy":     (c_happy,     0.88),
    "shy":       (c_shy,       0.66),
    "whale":     (c_whale,     0.72),
    "eat":       (c_eat,       0.74),
    "grab":      (c_grab,      0.46),
    "drop":      (c_drop,      0.50),
    "zoom_up":   (c_zoom_up,   0.34),
    "zoom_down": (c_zoom_down, 0.34),
    "wake":      (c_wake,      0.78),
    "work":      (c_work,      0.40),
    "remind":    (c_remind,    0.82),
}


def write_wav(name, y, peak):
    y = np.asarray(y, dtype=np.float64)
    m = np.max(np.abs(y))
    if m > 0:
        y = y / m * peak
    pcm = np.clip(y * 32767.0, -32768.0, 32767.0).astype("<i2")
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path, len(pcm) * 2, len(pcm) / SR


def main():
    os.makedirs(OUT, exist_ok=True)
    total = 0
    print(f"输出目录 {OUT}")
    print(f"{'名称':<11}{'时长':>8}{'大小':>9}")
    for name, (fn, peak) in CUES.items():
        path, nbytes, dur = write_wav(name, fn(), peak)
        total += nbytes
        print(f"  {name:<11}{dur * 1000:>6.0f}ms{nbytes / 1024:>8.1f}K")
    print(f"  合计 {len(CUES)} 条 / {total / 1024:.0f} KB")


if __name__ == "__main__":
    main()
