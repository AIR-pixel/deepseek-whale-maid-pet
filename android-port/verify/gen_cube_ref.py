# -*- coding: utf-8 -*-
"""生成 `x ** 3` 的 Python 参考值，用来钉死跨语言幂运算的口径。

背景
----
`sink` 原语的形状是 `ease_in(x) = x ** 3`（打瞌睡的缓慢低头段）。
Python 的 `float ** int` 走 C 运行库的 `pow()`，而搬到 JVM 上有两种写法：

    x * x * x           两次乘法
    Math.pow(x, 3.0)    JVM 的 pow

两者都可能和 CPython 差若干 ULP。这个脚本把**实际会出现的那批 x**
（`ph / 0.78` 和 `(ph - 0.78) / 0.22`，都在 [0,1) 区间）连同 Python 结果导出，
让 JVM 复算，看哪种写法更接近。

输出 TSV：x 的十六进制 <TAB> x**3 的十六进制
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    # 1) 复刻 sink / hop 里真实出现的 x：[0,1) 上的分段采样
    xs = []
    periods = set()
    with open(os.path.join(ROOT, "content", "actions.json"), encoding="utf-8") as f:
        data = json.load(f)
    for name, d in (data.get("motions") or {}).items():
        for terms in (d.get("channels") or {}).values():
            for term in terms:
                if term.get("k") in ("sink", "hop") and "period" in term:
                    periods.add(float(term["period"]))
    for name, d in (data.get("motions") or {}).items():
        for key, term in (d.get("defs") or {}).items():
            if term.get("k") in ("sink", "hop") and "period" in term:
                periods.add(float(term["period"]))

    # 与 motion_regression 相同的采样密度：3 个周期 / 150 步
    for period in sorted(periods) or (3.4,):
        for i in range(151):
            t = period * 3.0 * i / 150
            ph = (t % period) / period
            if ph < 0.78:
                xs.append(ph / 0.78)
            else:
                xs.append((ph - 0.78) / 0.22)

    # 2) 再补 [0,1) 上的均匀网格，把边界和中间值都覆盖住
    for i in range(1001):
        xs.append(i / 1000.0)

    # 3) 去重，保持顺序
    seen = set()
    uniq = []
    for x in xs:
        if 0.0 <= x < 1.0 and x not in seen:
            seen.add(x)
            uniq.append(x)

    out = os.path.join(HERE, "cube_calls.tsv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for x in uniq:
            f.write("%s\t%s\n" % (x.hex(), (x ** 3).hex()))

    print("sink/hop 涉及的 period: %s" % sorted(periods))
    print("cube 样本数（去重后）: %d" % len(uniq))
    print("已写出: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
