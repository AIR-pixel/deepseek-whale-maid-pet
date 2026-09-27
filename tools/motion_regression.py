# -*- coding: utf-8 -*-
"""动效回归比对：把 motion 模块的数值输出与基准快照逐点比对。

用途
----
`src/motion.py` 从"每个素材一段写死的 if-else"改成"数据驱动的曲线引擎"时，
必须证明**输出一个数值都没变**。光靠肉眼看预览图是不够的（幅度差 0.3px 看不出来，
但会在小尺寸下被放大）。这个脚本做的是逐点数值比对。

用法
----
    python tools/motion_regression.py dump  ref.json                 # 采样当前模块
    python tools/motion_regression.py dump  ref.json --module old.py # 采样指定文件
    python tools/motion_regression.py check ref.json                 # 与基准比对

`check` 返回码 0 表示完全一致（abs_tol=0），1 表示有差异（会打印前几处）。
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODULE = os.path.join(os.path.dirname(HERE), "src", "motion.py")

# 采样点：尺寸档要覆盖冒烟测试里扫过的那些，缩放系数取实际会出现的极值
SCALES = (0.5, 1.0, 460 / 280.0, 2.0)
HEIGHTS = (80, 90, 130, 190, 280, 340, 380, 460, 520, 560)
STEPS = 150


def load_module(path):
    """按文件路径加载 motion 模块（绕过 sys.modules 缓存，可用于 A/B 两份文件）"""
    spec = importlib.util.spec_from_file_location("motion_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sample(mod):
    out = {"cycle": {}, "visual_scale": {}, "pad": {}, "scale_for": {}, "params": {}}
    names = sorted(mod.CYCLE)

    for n in names:
        out["cycle"][n] = mod.cycle(n)
    for n in names:
        out["visual_scale"][n] = mod.VISUAL_SCALE.get(n, 1.0)
    for h in HEIGHTS:
        out["pad"][str(h)] = mod.pad_for(h)
        out["scale_for"][str(h)] = mod.scale_for(h)

    for n in names:
        cyc = mod.cycle(n)
        rows = []
        for i in range(STEPS + 1):
            # 三个完整周期，足以覆盖 doze / happy 这类分段曲线回到起点
            t = cyc * 3.0 * i / STEPS
            for sc in SCALES:
                rows.append([round(v, 12) for v in mod.params(n, t, sc)])
        # 负时间（状态刚切换时 _t - _state_t0 可能瞬时为负）
        rows.append([round(v, 12) for v in mod.params(n, -0.5, 1.0)])
        out["params"][n] = rows
    return out


def compare(ref, cur):
    diffs = []

    def walk(path, a, b):
        if isinstance(a, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a or k not in b:
                    diffs.append(f"{path}.{k}: 键缺失 (ref={k in a}, cur={k in b})")
                else:
                    walk(f"{path}.{k}", a[k], b[k])
        elif isinstance(a, list):
            if len(a) != len(b):
                diffs.append(f"{path}: 长度 {len(a)} != {len(b)}")
                return
            for i, (x, y) in enumerate(zip(a, b)):
                walk(f"{path}[{i}]", x, y)
        else:
            if a != b:
                diffs.append(f"{path}: {a!r} != {b!r}")

    walk("", ref, cur)
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dump", "check"])
    ap.add_argument("path")
    ap.add_argument("--module", default=DEFAULT_MODULE)
    args = ap.parse_args()

    if not os.path.exists(args.module):
        print(f"模块不存在: {args.module}")
        return 2

    cur = sample(load_module(args.module))

    if args.mode == "dump":
        with open(args.path, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, sort_keys=True)
        n_params = sum(len(v) for v in cur["params"].values())
        print(f"已写出基准: {args.path}")
        print(f"  素材 {len(cur['params'])} 个 / 参数采样 {n_params} 组")
        return 0

    with open(args.path, encoding="utf-8") as f:
        ref = json.load(f)
    diffs = compare(ref, cur)
    if diffs:
        print(f"== 不一致：{len(diffs)} 处 ==")
        for d in diffs[:20]:
            print("   -", d)
        if len(diffs) > 20:
            print(f"   …… 另有 {len(diffs) - 20} 处")
        return 1
    n_params = sum(len(v) for v in cur["params"].values())
    print(f"== 完全一致 ==  {len(cur['params'])} 个素材 × {n_params} 组采样，逐点误差 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
