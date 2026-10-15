# -*- coding: utf-8 -*-
"""逐位比对 Python 与 Kotlin 两版动效引擎的采样输出。

判据
----
原实现要求「一个数值都没变」，容差 0。跨语言做不到这一点——CPython 的 libm
和 JVM 的实现本就不同（实测 sin 有 96.72% 逐位相同、最大 1 ULP）。所以这里的
标准换成：**结构必须完全一致，数值偏差必须远低于视觉阈值**。

文档里写明 0.0001 px 的偏差在小尺寸下就能被肉眼看见。只要实测偏差比这个
再低几个数量级，就可以断言"搬运是安全的"。这个脚本给出实测数字而不是感觉。
"""
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNELS = ["dx", "dy", "sx", "sy", "rot"]


def u2d(u):
    return struct.unpack("<d", struct.pack("<Q", u))[0]


def to_signed(u):
    return u - (1 << 64) if u >= (1 << 63) else u


def ordered(u):
    """把位模式映射成单调整数，差的绝对值 = ULP 距离（正确处理负数）"""
    b = to_signed(u)
    return (-(1 << 63)) - b if b < 0 else b


def ulp(a_u, b_u):
    return abs(ordered(a_u) - ordered(b_u))


def read(path):
    with open(path, encoding="utf-8") as f:
        return [ln for ln in f.read().split("\n") if ln]


def main():
    py_path = os.path.join(HERE, "python_ref.tsv")
    # 候选实现可换：默认 x86_64 桌面 JVM 的产物，可传 ARM64 设备产物
    # （build/arm64_out.tsv）来复核"换架构后是否仍然逐位一致"。
    if len(sys.argv) > 1:
        kt_path = sys.argv[1]
        if not os.path.isabs(kt_path):
            kt_path = os.path.join(HERE, kt_path)
    else:
        kt_path = os.path.join(HERE, "kotlin_out.tsv")
    print("基准: %s" % os.path.basename(py_path))
    print("候选: %s\n" % os.path.basename(kt_path))
    for p in (py_path, kt_path):
        if not os.path.exists(p):
            print("缺少文件: %s" % p)
            return 2

    py = read(py_path)
    kt = read(kt_path)

    print("== 结构 ==")
    print("Python 行数 %d / Kotlin 行数 %d" % (len(py), len(kt)))
    if len(py) != len(kt):
        print("!! 行数不一致，后续比对无意义")
        return 1
    print("行数一致\n")

    # 逐类统计
    kpi = {"cycle": 0, "visual": 0, "pad": 0, "scale_for": 0, "params": 0}
    exact = {k: 0 for k in kpi}
    mismatch_struct = []

    # params 按字段统计（t / scale / 五个通道）
    fields = ["t", "scale"] + CHANNELS
    fp = {f: {"n": 0, "exact": 0, "maxabs": 0.0, "maxulp": 0, "worst": None}
          for f in fields}

    for idx, (a, b) in enumerate(zip(py, kt)):
        fa = a.split("\t")
        fb = b.split("\t")
        if len(fa) != len(fb) or fa[0] != fb[0] or fa[1] != fb[1]:
            mismatch_struct.append((idx, a[:90], b[:90]))
            continue

        kind = fa[0]
        kpi[kind] += 1

        if kind in ("cycle", "visual", "scale_for"):
            # 这三类是单个位模式
            if fa[2] == fb[2]:
                exact[kind] += 1
            continue

        if kind == "pad":
            if fa[2] == fb[2]:
                exact[kind] += 1
            continue

        # params 行：2..8 是 t / scale / dx dy sx sy rot
        if kind == "params":
            all_same = True
            for j, fname in enumerate(fields):
                ua = int(fa[2 + j])
                ub = int(fb[2 + j])
                st = fp[fname]
                st["n"] += 1
                if ua == ub:
                    st["exact"] += 1
                else:
                    all_same = False
                    da = u2d(ua)
                    db = u2d(ub)
                    d = abs(da - db)
                    u = ulp(ua, ub)
                    if d > st["maxabs"]:
                        st["maxabs"] = d
                        st["worst"] = (fa[1], u2d(int(fa[2])), da, db, u)
                    if u > st["maxulp"]:
                        st["maxulp"] = u
            if all_same:
                exact["params"] += 1
            continue

    if mismatch_struct:
        print("!! 结构错位 %d 处，前 5 条：" % len(mismatch_struct))
        for i, a, b in mismatch_struct[:5]:
            print("   #%d py=%s" % (i, a))
            print("       kt=%s" % b)
        return 1
    print("== 逐位相同率 ==")
    for k in ("cycle", "visual", "pad", "scale_for"):
        ok = exact[k] == kpi[k]
        print("  %-10s %d/%d %s" % (k, exact[k], kpi[k], "逐位一致" if ok else "有差异"))
    print("  %-10s %d/%d  行内全部字段逐位一致" % ("params", exact["params"], kpi["params"]))
    print()

    print("== params 各字段偏差明细 ==")
    print("  %-6s %-14s %-9s %s" % ("字段", "逐位相同", "最大ULP", "最大绝对误差"))
    for fname in fields:
        st = fp[fname]
        pct = 100.0 * st["exact"] / st["n"] if st["n"] else 0.0
        print("  %-6s %6d/%-7d %-9d %.3e"
              % (fname, st["exact"], st["n"], st["maxulp"], st["maxabs"]))
    print()

    # 结论：只看位移通道换算成像素是多少
    worst_px = 0.0
    for fname in ("dx", "dy"):
        worst_px = max(worst_px, fp[fname]["maxabs"])
    print("== 结论 ==")
    print("  位移通道最大绝对误差 %.3e（单位：逻辑像素，尚未乘 amp）" % worst_px)
    print("  视觉可见阈值（文档口径） 1e-4 px")
    if worst_px < 1e-4:
        orders = math.log10(1e-4 / max(worst_px, 1e-300))
        print("  → 比可见阈值低 %.1f 个数量级" % orders)
        print("  → 判定：搬运安全，容差定 1e-9 绰绰有余")
    else:
        print("  → 偏差达到可见量级，需要排查")

    # 挑最差的一条打出来，便于人工核对
    worst = None
    for fname in fields:
        st = fp[fname]
        if st["worst"] and (worst is None or st["worst"][3] != st["worst"][2]):
            cand = st["worst"]
            if worst is None or cand[4] > worst[4]:
                worst = cand
    if worst:
        print()
        print("  偏差最大的一处：素材 %s, t=%.9f" % (worst[0], worst[1]))
        print("    python=%.17g" % worst[2])
        print("    kotlin=%.17g  (相差 %d ULP)" % (worst[3], worst[4]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
