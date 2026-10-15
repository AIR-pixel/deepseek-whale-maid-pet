#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把动效引擎打成 dex jar，用 app_process 在设备上直接跑 —— 不需要安装 APK。

动机：MIUI/HyperOS 上 adb install 会被「USB 安装」开关拦掉
（INSTALL_FAILED_USER_RESTRICTED），但 app_process 不受该策略影响。
于是可以在真实 ARM64 的 ART 上量引擎开销、并复核 Math.sin 的位级行为。

用法：
    python build_bench.py                # 构建 + 推送 + 跑全部
    python build_bench.py --build-only
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
DEV = "/data/local/tmp/dpet"

SDK = r"C:\Users\air\AppData\Local\Android\Sdk"
BUILD_TOOLS = os.path.join(SDK, "build-tools", "37.0.0")
PLATFORM_JAR = os.path.join(SDK, "platforms", "android-37.0", "android.jar")
ADB = r"C:\Program Files\platform-tools\adb.exe"

JDK = r"C:\Program Files\Microsoft\jdk-21.0.7.6-hotspot"
KOTLINC = os.path.join(HERE, "tools", "kotlinc", "bin", "kotlinc.bat")
KOTLIN_STDLIB = os.path.join(HERE, "tools", "kotlinc", "lib", "kotlin-stdlib.jar")
D8 = os.path.join(BUILD_TOOLS, "d8.bat")

SRC_DIRS = [
    os.path.join(HERE, "core"),
    os.path.join(HERE, "verify"),
    os.path.join(HERE, "bench", "src"),
]

BENCH_MAIN = "dpet.bench.BenchKt"
VERIFY_MAIN = "dpet.verify.MotionVerifyKt"


def step(m):
    print("\n==> %s" % m, flush=True)


def log(m):
    print("  %s" % m, flush=True)


def run(cmd, check=True):
    full = list(cmd)
    if full[0].lower().endswith(".bat"):
        full = ["cmd", "/c"] + full
    env = dict(os.environ)
    env["JAVA_HOME"] = JDK
    p = subprocess.run(full, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    if p.returncode != 0 and check:
        print("\n!! 失败: %s" % " ".join(full))
        print("--- stdout ---\n%s" % (p.stdout or "")[-3000:])
        print("--- stderr ---\n%s" % (p.stderr or "")[-3000:])
        sys.exit(2)
    return p


def adb(args, check=True):
    return run([ADB] + args, check=check)


def build_jar():
    classes = os.path.join(BUILD, "bench-classes")
    if os.path.isdir(classes):
        shutil.rmtree(classes)
    os.makedirs(classes)

    srcs = []
    for d in SRC_DIRS:
        srcs += sorted(glob.glob(os.path.join(d, "**", "*.kt"), recursive=True))
    log("源文件 %d 个" % len(srcs))

    run([KOTLINC, "-classpath", PLATFORM_JAR, "-jvm-target", "17", "-nowarn",
         "-d", classes] + srcs)

    inputs = sorted(glob.glob(os.path.join(classes, "**", "*.class"), recursive=True))
    inputs.append(KOTLIN_STDLIB)

    jar = os.path.join(BUILD, "bench.jar")
    if os.path.exists(jar):
        os.remove(jar)
    run([D8, "--lib", PLATFORM_JAR, "--min-api", "24", "--output", jar] + inputs)
    log("bench.jar = %.1f KB" % (os.path.getsize(jar) / 1024.0))
    return jar


def push_all(jar):
    adb(["shell", "mkdir", "-p", DEV], check=False)
    adb(["push", jar, "%s/bench.jar" % DEV])
    adb(["push", os.path.join(PROJ, "content", "actions.json"), "%s/actions.json" % DEV])
    sin_ref = os.path.join(HERE, "verify", "sin_calls.tsv")
    if os.path.exists(sin_ref):
        adb(["push", sin_ref, "%s/sin_calls.tsv" % DEV])


def shell_run(main_class, *args):
    cmd = "CLASSPATH=%s/bench.jar app_process /system/bin %s %s" % (
        DEV, main_class, " ".join(args))
    p = adb(["shell", cmd], check=False)
    out = (p.stdout or "") + (p.stderr or "")
    return out


def run_on_host(actions_json):
    """同一份 Bench 编译成 .class，在桌面 JVM 上跑，作为 x86_64 基线。

    Bench 只用 dpet.core，而 core 零 Android 依赖，所以同一份源码两边都能编。
    """
    classes = os.path.join(BUILD, "host-classes")
    if os.path.isdir(classes):
        shutil.rmtree(classes)
    os.makedirs(classes)

    srcs = []
    for d in (os.path.join(HERE, "core"), os.path.join(HERE, "bench", "src")):
        srcs += sorted(glob.glob(os.path.join(d, "**", "*.kt"), recursive=True))

    run([KOTLINC, "-jvm-target", "17", "-nowarn", "-d", classes] + srcs)

    java = os.path.join(JDK, "bin", "java.exe")
    cp = classes + os.pathsep + KOTLIN_STDLIB
    p = run([java, "-cp", cp, "dpet.bench.BenchKt", actions_json], check=False)
    print((p.stdout or "") + (p.stderr or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--host", action="store_true",
                    help="只跑桌面 JVM 基线（x86_64），不碰设备")
    args = ap.parse_args()

    actions_json = os.path.join(PROJ, "content", "actions.json")

    if args.host:
        step("桌面 JVM 基线（x86_64）")
        run_on_host(actions_json)
        return

    step("编译 + dex")
    jar = build_jar()

    if args.build_only:
        return

    step("推送到设备")
    push_all(jar)

    step("设备侧：引擎基准 + sin 位模式")
    print(shell_run(BENCH_MAIN, "%s/actions.json" % DEV,
                    "%s/sin_calls.tsv" % DEV, "%s/sin_out.tsv" % DEV))

    step("设备侧：全量采样（给 compare_bits.py 用）")
    print(shell_run(VERIFY_MAIN, "%s/actions.json" % DEV, "%s/arm64_out.tsv" % DEV))

    step("取回结果")
    for name in ("sin_out.tsv", "arm64_out.tsv"):
        dst = os.path.join(BUILD, name)
        p = adb(["pull", "%s/%s" % (DEV, name), dst], check=False)
        if os.path.exists(dst):
            log("%s = %.1f KB" % (name, os.path.getsize(dst) / 1024.0))
        else:
            log("%s 未取回: %s" % (name, (p.stderr or "").strip()))


if __name__ == "__main__":
    main()
