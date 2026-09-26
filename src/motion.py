# -*- coding: utf-8 -*-
"""程序化动效：为每个状态生成独立的运动曲线。

设计要点
--------
* 返回 (dx, dy, sx, sy, rot)，单位：逻辑像素 / 倍数 / 角度。
* 位移幅度以 **REF_H=280 为基准**，调用方按实际角色高度传入 scale_for(高度)，
  这样 190 高度和 460 高度下的观感一致（否则大尺寸时动效几乎看不见）；
  高度低于 REF_H*SCALE_MIN 时不再继续缩小，避免迷你尺寸下动效被抹平。
* 变换锚点是**脚底中心**——呼吸时脚不动、蹦跳时整个人离地、压扁时从脚底往上缩，
  不会出现"角色在窗口里乱飘"的廉价感。
* 帧间一致性天然 100%：所有帧都由同一张立绘实时变换而来，不会像 AI 生成序列帧
  那样出现五官漂移、描边抖动。
* 曲线用相位驱动（t 为进入该状态后的秒数），切换状态时相位归零，避免动效从半空中开始。
"""
import math

TAU = math.pi * 2
REF_H = 280.0          # 幅度基准高度（逻辑像素）

# 幅度缩放下限：高度低于 REF_H*SCALE_MIN 时不再继续等比缩小。
# 否则调到迷你尺寸（80px）时呼吸只剩 1px 出头，肉眼等于静止。
# 因为窗口边距有一项固定的 +12px 底数，钳住下限也不会让动效越界。
SCALE_MIN = 0.5


def _sin(t, period, phase=0.0):
    return math.sin(TAU * t / period + phase)


def _pulse(t, period, duty=0.4):
    """周期脉冲：一个周期内前 duty 比例为 1，其余为 0"""
    return 1.0 if (t % period) / period < duty else 0.0


def _ease_in(x):
    return x ** 3


def _ease_out(x):
    return 1.0 - (1.0 - x) ** 3


# 每个素材一个完整动效循环的时长（秒），供预览采样与测试使用
CYCLE = {
    "idle_open": 3.6, "idle_blink": 3.6,
    "work_keypress": 0.92, "work_desk": 0.92,
    "eat": 1.05, "doze": 3.4, "sleep": 4.6,
    "whale": 5.4, "blindfold": 0.5, "happy": 0.95,
}


def cycle(name):
    return CYCLE.get(name, 3.0)


# 视觉缩放修正：各素材构图不同，统一按"图片高度"缩放会让横躺的鲸鱼、带桌子的
# 工作图显得比别人大一圈。这里按体量手工配平，让切换状态时的视觉大小平稳。
# 1.0 = 不做修正，想微调只改这里。
VISUAL_SCALE = {
    "whale": 0.78,        # 横躺鲸鱼，视觉体量偏大
    "work_desk": 0.90,    # 画面含桌子和马克杯，占面积大
    "sleep": 0.95,
}


def __raw(name, t):
    """未缩放的原始动效参数"""

    # ---- 待机：呼吸
    if name in ("idle_open", "idle_blink"):
        b = _sin(t, 3.6)
        return (0.0, b * 4.8, 1.0, 1.0 + b * 0.009, 0.0)

    # ---- 工作：打字律动（两组不同周期的脉冲叠加，避免机械节拍）
    if name in ("work_keypress", "work_desk"):
        tap = min(_pulse(t, 0.17, 0.36) + _pulse(t, 0.23, 0.28), 1.0)
        sway = _sin(t, 3.0) * 1.2
        return (sway, -2.6 * tap, 1.0, 1.0, sway * 0.16)

    # ---- 干饭：咀嚼
    if name == "eat":
        c = _sin(t, 1.05)
        return (0.0, c * 3.4, 1.0 + c * 0.003, 1.0 - c * 0.003, _sin(t, 2.1) * 0.8)

    # ---- 犯困：缓慢低头 -> 猛地抬头（打瞌睡的经典曲线）
    if name == "doze":
        ph = (t % 3.4) / 3.4
        if ph < 0.78:
            sink = _ease_in(ph / 0.78) * 11.0
        else:
            sink = (1.0 - _ease_out((ph - 0.78) / 0.22)) * 11.0
        return (0.0, sink, 1.0, 1.0 - sink * 0.005, sink * 0.16)

    # ---- 睡觉：缓慢深呼吸，幅度比待机大
    if name == "sleep":
        b = _sin(t, 4.6)
        return (0.0, b * 2.0, 1.0 + b * 0.006, 1.0 + b * 0.013, 0.0)

    # ---- 鲸鱼原型：水里漂浮
    if name == "whale":
        dx = _sin(t, 5.4) * 9.0
        return (dx, _sin(t, 3.1) * 4.2, 1.0, 1.0, _sin(t, 5.4) * 2.4)

    # ---- 蒙眼：慌张的小幅高频抖动（两个不同频率叠加，更像发抖）
    if name == "blindfold":
        dx = math.sin(t * 37.0) * 1.9 + math.sin(t * 23.0) * 0.9
        return (dx, math.sin(t * 31.0) * 0.8, 1.0, 1.0, dx * 0.32)

    # ---- 开心：蹲下蓄力 -> 跳起 -> 落地缓冲
    if name == "happy":
        ph = (t % 0.95) / 0.95
        if ph < 0.10:                       # 蓄力下蹲
            k = ph / 0.10
            return (0.0, 2.8 * k, 1.0 + 0.07 * k, 1.0 - 0.08 * k, 0.0)
        if ph < 0.80:                       # 腾空
            k = (ph - 0.10) / 0.70
            return (0.0, -math.sin(k * math.pi) * 16.0, 1.0, 1.0, 0.0)
        k = math.sin((ph - 0.80) / 0.20 * math.pi)   # 落地缓冲
        return (0.0, 0.0, 1.0 + 0.06 * k, 1.0 - 0.07 * k, 0.0)

    return (0.0, 0.0, 1.0, 1.0, 0.0)


def scale_for(height):
    """由角色高度推出幅度缩放系数（带下限，见 SCALE_MIN）"""
    return max(height / REF_H, SCALE_MIN)


def params(name, t, scale=1.0):
    """返回该素材在 t 时刻的 (dx, dy, sx, sy, rot)。

    scale 由 scale_for(实际高度) 给出；旋转是角度，不参与缩放。
    """
    dx, dy, sx, sy, rot = __raw(name, max(t, 0.0))
    return (dx * scale, dy * scale, sx, sy, rot)


def pad_for(height):
    """给定角色高度，算出需要预留的边距（覆盖跳跃位移 + 旋转外溢）"""
    return int(round(12 + height * 0.042))
