# -*- coding: utf-8 -*-
"""程序化动效引擎：曲线由数据描述，解释执行。

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

曲线为什么是数据
----------------
2026-09-27 之前，每个素材的曲线是这里的一段 `if name == "...":`，改一个动作就要
改代码、重新打包。为了让桌宠能**从远端接收新动作**，曲线改由 `content/actions.json`
的 `motions` 段描述，本模块只负责解释执行。

引擎只认识下面这几个**具名原语**，不认识的一律跳过（前向兼容：新版本加的原语
在旧程序上只是不生效，不会崩）：

============  ==============================================================
原语           含义
============  ==============================================================
``const``     常量增量，``v``
``sine``      正弦，``sin(2π·t/period + phase) × amp``
``freq``      按角频率振荡，``sin(omega·t) × amp``
``pulse_sum`` 多条周期脉冲求和后钳位，``min(Σpulse, max) × amp``
``sink``      缓慢下沉→猛地抬头（打瞌睡），形状固定、段点写死在引擎里
``hop``       蹲下蓄力→腾空→落地缓冲，形状固定；输出分量由所在通道决定
``ref``       引用同素材里已算出的量，``值 × amp``
============  ==============================================================

**中间量**用 ``save`` 声明、用 ``ref`` 取用，两个键名分开是刻意的：早期版本两边
都叫 ``sig``，结果 ref 项自己也被当成一次声明，把上游信号表覆盖成 0（doze 的 rot
就是这么变成 0 的）。现在 ``save`` 只在"产生值"的原语上出现。

``ref`` 有两种引用方式：``{"sig": "名字"}`` 取 ``save`` 存下的中间量，
``{"ch": "dx"}`` 取某个**已算完**通道的累计增量。通道求值顺序固定为
``dy → dx → sx → sy → rot``，所以 rot 可以引用 dx（blindfold、work 就是这么用的），
sy 可以引用 dy，反过来不行。

为什么要允许 ``save_scale``：eat 的位移是 ``sin×3.4``，但缩放通道用的是**裸 sin**
（``1.0 + sin×0.003``）。默认存的是"已乘 amp"的值（对 sink 正好是位移本身），
eat 显式把 ``save_scale`` 设成 1.0 来拿裸值。两条路都保留，是为了能逐位复刻原曲线。

**缩放通道的基准是 1.0**（``BASE``），数据里不要再写 ``const 1.0`` —— 会叠加成 2.0。
留 1.0 作默认值是为了安全：数据写漏了顶多不动，不会把立绘压成一条线。
"""
import json
import math
import os

TAU = math.pi * 2
REF_H = 280.0          # 幅度基准高度（逻辑像素）

# 幅度缩放下限：高度低于 REF_H*SCALE_MIN 时不再继续等比缩小。
# 否则调到迷你尺寸（80px）时呼吸只剩 1px 出头，肉眼等于静止。
# 因为窗口边距有一项固定的 +12px 底数，钳住下限也不会让动效越界。
SCALE_MIN = 0.5

# 通道求值顺序。ref 只能引用**排在自己前面**的通道，见模块文档。
ORDER = ("dy", "dx", "sx", "sy", "rot")
BASE = {"dy": 0.0, "dx": 0.0, "sx": 1.0, "sy": 1.0, "rot": 0.0}

DEFAULT_CYCLE = 3.0
DEFAULT_PARAMS = (0.0, 0.0, 1.0, 1.0, 0.0)


def _sin(t, period, phase=0.0):
    return math.sin(TAU * t / period + phase)


def _pulse(t, period, duty):
    """周期脉冲：一个周期内前 duty 比例为 1，其余为 0"""
    return 1.0 if (t % period) / period < duty else 0.0


def _ease_in(x):
    return x ** 3


def _ease_out(x):
    return 1.0 - (1.0 - x) ** 3


# ---------------------------------------------------------------- 原语

def _ev_const(term, t, ch, ctx):
    v = float(term.get("v", 0.0))
    return v, v


def _ev_sine(term, t, ch, ctx):
    raw = _sin(t, float(term["period"]), float(term.get("phase", 0.0)))
    return raw, raw * float(term.get("amp", 1.0))


def _ev_freq(term, t, ch, ctx):
    raw = math.sin(float(term["omega"]) * t)
    return raw, raw * float(term.get("amp", 1.0))


def _ev_pulse_sum(term, t, ch, ctx):
    total = 0.0
    for period, duty in term["items"]:
        total += _pulse(t, float(period), float(duty))
    raw = min(total, float(term.get("max", 1.0)))
    return raw, raw * float(term.get("amp", 1.0))


def _ev_sink(term, t, ch, ctx):
    """打瞌睡：0.78 的时间缓慢低头（ease-in），剩下 0.22 猛地抬头（ease-out）。

    段点 0.78 / 0.22 写死在引擎里而不是做成参数——它就是这个动作的形状，
    开放成参数只会让发布侧更容易写错。
    """
    period = float(term["period"])
    ph = (t % period) / period
    if ph < 0.78:
        raw = _ease_in(ph / 0.78)
    else:
        raw = 1.0 - _ease_out((ph - 0.78) / 0.22)
    return raw, raw * float(term.get("amp", 1.0))


def _ev_hop(term, t, ch, ctx):
    """蹲下蓄力（0~0.10）→ 腾空（0.10~0.80）→ 落地缓冲（0.80~1.0）。

    输出哪一路由它所在的通道决定：dy 出竖直位移，sx / sy 出缩放**增量**
    （调用方基准是 1.0，所以返回 0.07 表示整体放大 7%）。
    段点同样写死，和 sink 一个道理。
    """
    period = float(term["period"])
    ph = (t % period) / period
    if ch == "dy":
        if ph < 0.10:
            return 0.0, float(term.get("crouch_amp", 0.0)) * (ph / 0.10)
        if ph < 0.80:
            k = (ph - 0.10) / 0.70
            return 0.0, -math.sin(k * math.pi) * float(term.get("amp", 0.0))
        return 0.0, 0.0
    if ch == "sx":
        if ph < 0.10:
            return 0.0, float(term.get("crouch_sx", 0.0)) * (ph / 0.10)
        if ph < 0.80:
            return 0.0, 0.0
        k = math.sin((ph - 0.80) / 0.20 * math.pi)
        return 0.0, float(term.get("land_sx", 0.0)) * k
    if ch == "sy":
        if ph < 0.10:
            return 0.0, -float(term.get("crouch_sy", 0.0)) * (ph / 0.10)
        if ph < 0.80:
            return 0.0, 0.0
        k = math.sin((ph - 0.80) / 0.20 * math.pi)
        return 0.0, -float(term.get("land_sy", 0.0)) * k
    return 0.0, 0.0


def _ev_ref(term, t, ch, ctx):
    amp = float(term.get("amp", 1.0))
    if "sig" in term:
        name = term["sig"]
        if name not in ctx["sigs"]:
            raise KeyError(f"引用了未定义的信号 {name!r}")
        return 0.0, ctx["sigs"][name] * amp
    name = term.get("ch")
    if name not in ctx["chans"]:
        raise KeyError(f"引用了尚未求值的通道 {name!r}（顺序必须是 {' → '.join(ORDER)}）")
    return 0.0, ctx["chans"][name] * amp


PRIMITIVES = {
    "const": _ev_const,
    "sine": _ev_sine,
    "freq": _ev_freq,
    "pulse_sum": _ev_pulse_sum,
    "sink": _ev_sink,
    "hop": _ev_hop,
    "ref": _ev_ref,
}


# ---------------------------------------------------------------- 动作集合

class MotionSet:
    """一组素材的动效定义。构造后不可变，整体替换即可热加载。"""

    def __init__(self, motions, visual_scales=None):
        self._defs = _resolve(motions or {})
        self._vis = dict(visual_scales or {})
        self.unknown = sorted({t["k"] for d in self._defs.values()
                               for terms in d["channels"].values()
                               for t in terms if t.get("k") not in PRIMITIVES})

    def names(self):
        return sorted(self._defs)

    def has(self, name):
        return name in self._defs

    def cycle(self, name):
        d = self._defs.get(name)
        return d["cycle"] if d else DEFAULT_CYCLE

    def visual_scale(self, name):
        return self._vis.get(name, 1.0)

    def raw(self, name, t):
        """返回该素材在 t 时刻未缩放的 (dx, dy, sx, sy, rot)"""
        d = self._defs.get(name)
        if d is None:
            return DEFAULT_PARAMS
        total = dict(BASE)
        ctx = {"sigs": {}, "chans": {}}
        for ch in ORDER:
            acc = BASE[ch]
            for term in d["channels"].get(ch, ()):
                fn = PRIMITIVES.get(term.get("k"))
                if fn is None:
                    continue                      # 不认识的原语直接跳过
                raw, contrib = fn(term, t, ch, ctx)
                save = term.get("save")
                if save:
                    # 默认存"该原语对本通道的贡献值"（= raw × amp）；
                    # save_scale 用来显式换取别的口径，见模块文档的 eat 例子。
                    k = float(term.get("save_scale", term.get("amp", 1.0)))
                    ctx["sigs"][save] = raw * k
                acc = acc + contrib
            total[ch] = acc
            ctx["chans"][ch] = acc
        return (total["dx"], total["dy"], total["sx"], total["sy"], total["rot"])

    def params(self, name, t, scale=1.0):
        dx, dy, sx, sy, rot = self.raw(name, max(t, 0.0))
        return (dx * scale, dy * scale, sx, sy, rot)

    def cycles(self):
        return {n: self.cycle(n) for n in self._defs}

    def visual_scales(self):
        return dict(self._vis)


def _resolve(motions):
    """展开 inherit 链。子定义覆盖父定义，可只写 {"inherit": "父名"}。"""
    out = {}

    def build(name, seen):
        if name in out:
            return out[name]
        if name in seen:
            raise ValueError(f"动作继承成环: {name}")
        src = motions.get(name)
        if src is None:
            raise KeyError(f"继承了不存在的动作: {name}")
        parent = src.get("inherit")
        base_cycle, base_ch, base_defs = DEFAULT_CYCLE, {}, {}
        if parent:
            par = build(parent, seen | {name})
            base_cycle, base_ch, base_defs = par["cycle"], par["channels"], par["defs"]
        channels = dict(base_ch)
        channels.update(src.get("channels") or {})
        defs = dict(base_defs)
        defs.update(src.get("defs") or {})
        out[name] = {
            "cycle": float(src.get("cycle", base_cycle)),
            "channels": {ch: _expand(terms, defs) for ch, terms in channels.items()},
            "defs": defs,
        }
        return out[name]

    for name in list(motions):
        build(name, set())
    return out


def _expand(terms, defs):
    """把 {"$def": "名字"} 展开成 defs 里的完整原语"""
    out = []
    for term in terms:
        key = term.get("$def")
        if key is None:
            out.append(term)
        elif key in defs:
            out.append(defs[key])
        else:
            raise KeyError(f"引用了不存在的原语定义: {key}")
    return out


# ---------------------------------------------------------------- 内置默认实例

def builtin_path():
    """内置内容包的位置。测试可用 DPET_CONTENT_DIR 指到别处。"""
    root = os.environ.get("DPET_CONTENT_DIR")
    if root:
        return os.path.join(root, "actions.json")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "content", "actions.json")


def builtin_set():
    """读内置 content/actions.json 构造 MotionSet。

    读不到就返回空集合 —— 动效全静默（角色还能站、还能交互），
    绝不能让一个坏掉的数据文件把桌宠卡死在启动阶段。
    """
    try:
        with open(builtin_path(), encoding="utf-8") as f:
            data = json.load(f)
        vis = {k: v.get("visual_scale", 1.0) for k, v in (data.get("assets") or {}).items()}
        return MotionSet(data.get("motions"), vis)
    except Exception:
        return MotionSet({}, {})


_SET = builtin_set()

# 兼容旧接口：模块级函数都走内置实例。
CYCLE = _SET.cycles()
VISUAL_SCALE = _SET.visual_scales()


def cycle(name):
    return _SET.cycle(name)


def params(name, t, scale=1.0):
    """返回该素材在 t 时刻的 (dx, dy, sx, sy, rot)。

    scale 由 scale_for(实际高度) 给出；旋转是角度，不参与缩放。
    """
    return _SET.params(name, t, scale)


def scale_for(height):
    """由角色高度推出幅度缩放系数（带下限，见 SCALE_MIN）"""
    return max(height / REF_H, SCALE_MIN)


def pad_for(height):
    """给定角色高度，算出需要预留的边距（覆盖跳跃位移 + 旋转外溢）"""
    return int(round(12 + height * 0.042))
