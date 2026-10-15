# -*- coding: utf-8 -*-
"""捕获 motion.py 在真实采样中调用 math.sin 的每一次实参。

为什么要这么干
--------------
跨语言移植时，"逐点误差 0" 这条铁律会在 math.sin 上失效：
CPython 走 C 运行库的 sin()，JVM 走 Math.sin()，两者都只承诺
几 ULP 内的正确性，并不保证 bit-exact。

所以先别猜差异有多大 —— 直接**把真实调用过的参数全抓下来**，
交给 JVM 复算，量出实际差了多少。参数覆盖了所有原语路径：
sine（周期相位）/ freq（大 omega）/ hop（分段 sin）都在里面。

输出 TSV：参数(17 位十六进制往返) <TAB> Python sin 结果
用 float.hex() 而不是 repr()，保证跨语言传递不丢位。
"""
import importlib.util
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

calls = []
_orig_sin = math.sin


def _spy(x):
    r = _orig_sin(x)
    calls.append((float(x), r))
    return r


def load_motion():
    path = os.path.join(ROOT, "src", "motion.py")
    spec = importlib.util.spec_from_file_location("motion_spy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    # 必须在 motion 模块求值之前就把 math.sin 换掉：
    # motion 内部写的是 math.sin(...)，查的是 math 模块属性，所以能被截获。
    math.sin = _spy
    mod = load_motion()

    # 采样口径与 tools/motion_regression.py 完全一致，保证覆盖真实运行会出现的参数
    heights = (80, 90, 130, 190, 280, 340, 380, 460, 520, 560)
    scales = (0.5, 1.0, 460 / 280.0, 2.0)
    steps = 150

    for name in sorted(mod.CYCLE):
        cyc = mod.cycle(name)
        for i in range(steps + 1):
            t = cyc * 3.0 * i / steps
            for sc in scales:
                mod.params(name, t, sc)
        mod.params(name, -0.5, 1.0)

    for h in heights:
        mod.scale_for(h)
        mod.pad_for(h)

    # 去重（同一参数会被多个 scale 重复调用），保持首次出现顺序
    seen = set()
    uniq = []
    for x, r in calls:
        if x not in seen:
            seen.add(x)
            uniq.append((x, r))

    out = os.path.join(HERE, "sin_calls.tsv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for x, r in uniq:
            f.write("%s\t%s\n" % (x.hex(), r.hex()))

    print("sin 调用总数 %d，去重后 %d" % (len(calls), len(uniq)))
    xs = [x for x, _ in uniq]
    print("参数范围: %.6f .. %.6f" % (min(xs), max(xs)))
    print("已写出: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
