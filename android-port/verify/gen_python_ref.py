# -*- coding: utf-8 -*-
"""生成 Python 侧的采样基准（与 Kotlin 采样器同口径、同位模式编码）。

采样逻辑完全复刻 tools/motion_regression.py 的 sample()，只把输出形式
从 JSON 树换成扁平的 TSV 行，好让 Kotlin 侧逐行对齐。

数值一律写成 IEEE-754 原始位模式（无符号十进制），零歧义：
    Kotlin: java.lang.Long.toUnsignedString(d.toRawBits())
    Python: struct.unpack('<Q', struct.pack('<d', d))[0]
"""
import importlib.util
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCALES = (0.5, 1.0, 460 / 280.0, 2.0)
HEIGHTS = (80, 90, 130, 190, 280, 340, 380, 460, 520, 560)
STEPS = 150


def bits(d):
    return str(struct.unpack("<Q", struct.pack("<d", float(d)))[0])


def load_motion():
    path = os.path.join(ROOT, "src", "motion.py")
    spec = importlib.util.spec_from_file_location("motion_ref_side", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def params_line(name, t, scale, r):
    return "\t".join([
        "params", name, bits(t), bits(scale),
        bits(r[0]), bits(r[1]), bits(r[2]), bits(r[3]), bits(r[4]),
    ])


def main():
    mod = load_motion()
    names = sorted(mod.CYCLE)
    lines = []

    for n in names:
        lines.append("cycle\t%s\t%s" % (n, bits(mod.cycle(n))))
        lines.append("visual\t%s\t%s" % (n, bits(mod.VISUAL_SCALE.get(n, 1.0))))
    for h in HEIGHTS:
        lines.append("pad\t%d\t%d" % (h, mod.pad_for(h)))
        lines.append("scale_for\t%d\t%s" % (h, bits(mod.scale_for(h))))

    for n in names:
        cyc = mod.cycle(n)
        for i in range(STEPS + 1):
            # 运算顺序必须与 Kotlin 侧一致：((cyc * 3.0) * i) / STEPS
            t = cyc * 3.0 * i / STEPS
            for sc in SCALES:
                lines.append(params_line(n, t, sc, mod.params(n, t, sc)))
        lines.append(params_line(n, -0.5, 1.0, mod.params(n, -0.5, 1.0)))

    out = os.path.join(HERE, "python_ref.tsv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    n_params = sum(1 for ln in lines if ln.startswith("params\t"))
    print("Python 采样完成：%d 个素材，params 行 %d，总行数 %d" % (len(names), n_params, len(lines)))
    print("已写出: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
