# -*- coding: utf-8 -*-
"""一键重跑跨语言动效回归：Python 基准 → Kotlin 采样 → 逐位比对。

用法
----
    python android-port/verify/run_verify.py

什么时候该跑
------------
改动 `src/motion.py` 或 `android-port/core/Motion.kt` 之后**必须**跑。
理由和原项目坚持 abs_tol=0 是同一个：几 ULP 的偏差在预览图上根本看不出来，
但会在小尺寸下被放大成可见的抖动。肉眼看 GIF 给不了证据，这个链路给。

步骤
----
1. 编译 Kotlin 引擎 → motion.jar
2. Kotlin 采样 → kotlin_out.tsv
3. Python 采样 → python_ref.tsv
4. 逐位比对 → 报告

退出码 0 表示结构与偏差都在可接受范围内。
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = os.path.dirname(HERE)
PROJ = os.path.dirname(PORT)
JAR = os.path.join(HERE, "motion.jar")
ACTIONS = os.path.join(PROJ, "content", "actions.json")
KOTLINC = os.path.join(PORT, "tools", "kotlinc", "bin", "kotlinc.bat")
PY = sys.executable


def find_jdk():
    """优先环境变量，其次扫常见安装位置。避免把机主路径写死在脚本里。"""
    cand = os.environ.get("JAVA_HOME")
    if cand and os.path.exists(os.path.join(cand, "bin", "java.exe")):
        return cand
    patterns = (
        r"C:\Program Files\Microsoft\jdk-*",
        r"C:\Program Files\Java\jdk-*",
        r"C:\Program Files\Eclipse Adoptium\jdk-*",
        r"C:\Program Files\Android\Android Studio\jbr",
    )
    for pat in patterns:
        for d in sorted(glob.glob(pat), reverse=True):
            if os.path.exists(os.path.join(d, "bin", "java.exe")):
                return d
    return None


def step(desc, cmd):
    print("── %s" % desc)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        print("   !! 失败（退出码 %d）" % p.returncode)
        if p.stdout:
            print(p.stdout[-2000:])
        if p.stderr:
            print(p.stderr[-2000:])
        return False
    if p.stdout and p.stdout.strip():
        for ln in p.stdout.strip().splitlines():
            print("   " + ln)
    return True


def main():
    jdk = find_jdk()
    if not jdk:
        print("找不到 JDK。请设置 JAVA_HOME 指向 JDK 17 以上版本。")
        return 2
    java = os.path.join(jdk, "bin", "java.exe")
    print("JDK: %s\n" % jdk)

    if not os.path.exists(KOTLINC):
        print("找不到 kotlinc: %s" % KOTLINC)
        return 2

    env = dict(os.environ)
    env["JAVA_HOME"] = jdk

    # 1) 编译
    print("── 编译 Kotlin 引擎")
    p = subprocess.run(
        ["cmd", "/c", KOTLINC,
         os.path.join(PORT, "core", "MiniJson.kt"),
         os.path.join(PORT, "core", "Motion.kt"),
         os.path.join(HERE, "MotionVerify.kt"),
         "-include-runtime", "-d", JAR],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    if p.returncode != 0 or not os.path.exists(JAR):
        print("   !! 编译失败")
        print((p.stdout or "")[-3000:])
        print((p.stderr or "")[-3000:])
        return 1
    print("   已产出 motion.jar (%.1f MB)" % (os.path.getsize(JAR) / 1024 / 1024))

    # 2) Kotlin 采样
    if not step("Kotlin 采样", [java, "-Dstdout.encoding=UTF-8", "-jar", JAR,
                                ACTIONS, os.path.join(HERE, "kotlin_out.tsv")]):
        return 1

    # 3) Python 采样
    if not step("Python 采样", [PY, os.path.join(HERE, "gen_python_ref.py")]):
        return 1

    # 4) 比对（这一步的输出要完整露出来，它是结论本身）
    print("── 逐位比对\n")
    p = subprocess.run([PY, os.path.join(HERE, "compare_bits.py")],
                       text=True, encoding="utf-8", errors="replace")
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
