#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deepseek-pet 安卓 POC 打包链 —— 刻意不走 Gradle。

为什么不用 Gradle / AGP：
  Gradle 发行包 + AGP + Maven 依赖在境内拉取又慢又容易断，而这里的验证目标
  （动效跑不跑得动）根本用不到它们。手工链 aapt2 -> kotlinc -> d8 -> zipalign
  -> apksigner 全程只依赖已经装好的 SDK 与 JDK，迭代一轮约 10 秒。

用法：
    python build_poc.py            # 构建 + 安装到已连接设备
    python build_poc.py --no-install
    python build_poc.py --run      # 构建 + 安装 + 启动
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)                      # deepseek-pet/
BUILD = os.path.join(HERE, "build")

SDK = r"C:\Users\air\AppData\Local\Android\Sdk"
BUILD_TOOLS = os.path.join(SDK, "build-tools", "37.0.0")
PLATFORM_JAR = os.path.join(SDK, "platforms", "android-37.0", "android.jar")
ADB = r"C:\Program Files\platform-tools\adb.exe"

JDK = r"C:\Program Files\Microsoft\jdk-21.0.7.6-hotspot"
KOTLINC = os.path.join(HERE, "tools", "kotlinc", "bin", "kotlinc.bat")
KOTLIN_STDLIB = os.path.join(HERE, "tools", "kotlinc", "lib", "kotlin-stdlib.jar")

AAPT2 = os.path.join(BUILD_TOOLS, "aapt2.exe")
D8 = os.path.join(BUILD_TOOLS, "d8.bat")
ZIPALIGN = os.path.join(BUILD_TOOLS, "zipalign.exe")
APKSIGNER = os.path.join(BUILD_TOOLS, "apksigner.bat")
KEYTOOL = os.path.join(JDK, "bin", "keytool.exe")

MIN_SDK = "24"
TARGET_SDK = "37"
KEYSTORE = os.path.join(HERE, "debug.keystore")

SRC_DIRS = [os.path.join(HERE, "core"), os.path.join(HERE, "app", "src")]


def log(msg):
    print("  %s" % msg, flush=True)


def step(msg):
    print("\n==> %s" % msg, flush=True)


def run(cmd, cwd=None, env=None, check=True):
    """执行命令。.bat 需要用 cmd /c 包一层。"""
    full = list(cmd)
    if full[0].lower().endswith(".bat"):
        full = ["cmd", "/c"] + full

    e = dict(os.environ)
    e["JAVA_HOME"] = JDK
    if env:
        e.update(env)

    p = subprocess.run(full, cwd=cwd, env=e, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        if check:
            print("\n!! 命令失败: %s" % " ".join(full))
            print("--- stdout ---\n%s" % (p.stdout or "")[-4000:])
            print("--- stderr ---\n%s" % (p.stderr or "")[-4000:])
            sys.exit(2)
        return p
    return p


def preflight():
    missing = []
    for p in (PLATFORM_JAR, AAPT2, D8, ZIPALIGN, APKSIGNER, KOTLINC,
              KOTLIN_STDLIB, os.path.join(JDK, "bin", "java.exe")):
        if not os.path.exists(p):
            missing.append(p)
    if missing:
        print("缺少构建依赖：")
        for m in missing:
            print("  - %s" % m)
        sys.exit(1)


def prepare_assets():
    """把 content/ 与 assets/ 复制进 build/assets，作为 APK 的 assets。"""
    dst = os.path.join(BUILD, "assets")
    if os.path.isdir(dst):
        shutil.rmtree(dst)

    os.makedirs(os.path.join(dst, "content"))
    shutil.copy2(os.path.join(PROJ, "content", "actions.json"),
                 os.path.join(dst, "content", "actions.json"))

    pet_dst = os.path.join(dst, "pet")
    os.makedirs(pet_dst)
    n = 0
    for f in sorted(glob.glob(os.path.join(PROJ, "assets", "pet", "*.webp"))):
        shutil.copy2(f, os.path.join(pet_dst, os.path.basename(f)))
        n += 1
    log("assets: actions.json + %d 张立绘" % n)
    return dst


def link_resources(assets_dir):
    out = os.path.join(BUILD, "base.apk")
    cmd = [AAPT2, "link",
           "-I", PLATFORM_JAR,
           "--manifest", os.path.join(HERE, "app", "AndroidManifest.xml"),
           "-A", assets_dir,
           "--min-sdk-version", MIN_SDK,
           "--target-sdk-version", TARGET_SDK,
           "--version-code", "1",
           "--version-name", "1.0",
           "-o", out]
    run(cmd)
    log("base.apk = %.1f KB" % (os.path.getsize(out) / 1024.0))
    return out


def compile_kotlin():
    classes = os.path.join(BUILD, "classes")
    if os.path.isdir(classes):
        shutil.rmtree(classes)
    os.makedirs(classes)

    srcs = []
    for d in SRC_DIRS:
        srcs += sorted(glob.glob(os.path.join(d, "**", "*.kt"), recursive=True))
    if not srcs:
        print("没找到 Kotlin 源文件")
        sys.exit(1)
    log("源文件 %d 个" % len(srcs))

    cmd = [KOTLINC, "-classpath", PLATFORM_JAR, "-jvm-target", "17",
           "-nowarn", "-d", classes] + srcs
    run(cmd)
    log("编译产物 %d 个 class" % len(glob.glob(os.path.join(classes, "**", "*.class"),
                                              recursive=True)))
    return classes


def dex(classes_dir):
    dexdir = os.path.join(BUILD, "dex")
    if os.path.isdir(dexdir):
        shutil.rmtree(dexdir)
    os.makedirs(dexdir)

    inputs = sorted(glob.glob(os.path.join(classes_dir, "**", "*.class"), recursive=True))
    inputs.append(KOTLIN_STDLIB)
    run([D8, "--lib", PLATFORM_JAR, "--min-api", MIN_SDK,
         "--output", dexdir] + inputs)

    d = os.path.join(dexdir, "classes.dex")
    if not os.path.exists(d):
        print("d8 没有产出 classes.dex")
        sys.exit(1)
    log("classes.dex = %.1f KB" % (os.path.getsize(d) / 1024.0))
    return d


def pack(base_apk, dex_file):
    """把 classes.dex 塞进 aapt2 产出的 APK。"""
    out = os.path.join(BUILD, "unsigned.apk")
    if os.path.exists(out):
        os.remove(out)
    shutil.copy2(base_apk, out)
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(dex_file, "classes.dex")
    log("unsigned.apk = %.1f KB" % (os.path.getsize(out) / 1024.0))
    return out


def ensure_keystore():
    if os.path.exists(KEYSTORE):
        return
    run([KEYTOOL, "-genkeypair", "-keystore", KEYSTORE,
         "-alias", "androiddebugkey", "-storepass", "android",
         "-keypass", "android", "-keyalg", "RSA", "-keysize", "2048",
         "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US"])
    log("已生成调试签名 %s" % KEYSTORE)


def sign_and_align(unsigned_apk):
    aligned = os.path.join(BUILD, "aligned.apk")
    run([ZIPALIGN, "-f", "-p", "4", unsigned_apk, aligned])

    out = os.path.join(BUILD, "petperf.apk")
    if os.path.exists(out):
        os.remove(out)
    run([APKSIGNER, "sign", "--ks", KEYSTORE,
         "--ks-pass", "pass:android", "--key-pass", "pass:android",
         "--out", out, aligned])

    v = run([APKSIGNER, "verify", "--print-certs", out])
    log("签名校验: %s" % (v.stdout or "").strip().splitlines()[-1])
    log("petperf.apk = %.1f KB" % (os.path.getsize(out) / 1024.0))
    return out


def adb(args, check=True):
    return run([ADB] + args, check=check)


RUN_SECONDS = 70

# 悬浮窗：3 个降帧档各 8s + 起窗延迟 0.8s + 引擎基准约 2s，留余量
OVERLAY_SECONDS = 40
REMOTE_OUT = "/sdcard/Android/data/dpet.poc/files/perf.txt"
REMOTE_OVL = "/sdcard/Android/data/dpet.poc/files/overlay.txt"


def collect():
    """启动 → 等各阶段跑完 → 取回结果文件 → 打印。

    刻意合并成一次调用：沙箱里 adb server 每条命令都会重启，拆开很慢。
    """
    adb(["shell", "am", "force-stop", "dpet.poc"], check=False)
    adb(["shell", "am", "start", "-n", "dpet.poc/.PetPerfActivity"])
    print("  等待 %ds（warmup/timer25/vsync60/decim30/decim20/stress/engine）..."
          % RUN_SECONDS, flush=True)
    time.sleep(RUN_SECONDS)
    pull_and_print(REMOTE_OUT, "perf.txt", "PETPERF")


def collect_overlay():
    """悬浮窗路径：授权 → 起前台服务 → 等测量跑完 → 取回结果。

    SYSTEM_ALERT_WINDOW 是受控权限，正常要走设置里的开关；但 appops 可以直接给，
    不需要 GUI 交互。国产 ROM 另有"后台弹出界面"之类的自有开关，那一步绕不过，
    所以 addView 是否成功必须记录在结果里。
    """
    adb(["shell", "am", "force-stop", "dpet.poc"], check=False)
    adb(["shell", "appops", "set", "dpet.poc", "SYSTEM_ALERT_WINDOW", "allow"], check=False)
    p = adb(["shell", "appops", "get", "dpet.poc", "SYSTEM_ALERT_WINDOW"], check=False)
    log("appops SYSTEM_ALERT_WINDOW: %s" % (p.stdout or "").strip())

    adb(["shell", "am", "start", "-n", "dpet.poc/.OverlayLauncherActivity"])
    print("  等待 %ds（ovl60 / ovl30 / ovl20 / engine）..." % OVERLAY_SECONDS, flush=True)
    time.sleep(OVERLAY_SECONDS)
    pull_and_print(REMOTE_OVL, "overlay.txt", "PETOVL")


def pull_and_print(remote, local_name, log_tag):
    local = os.path.join(BUILD, local_name)
    if os.path.exists(local):
        os.remove(local)
    adb(["pull", remote, local], check=False)

    print("\n---- 设备实测 ----")
    if os.path.exists(local):
        with open(local, encoding="utf-8", errors="replace") as f:
            print(f.read())
    else:
        print("没取到 %s，改看 logcat：" % remote)
        p = adb(["logcat", "-d", "-s", log_tag], check=False)
        print((p.stdout or "")[-4000:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--collect", action="store_true",
                    help="全屏基准：安装 + 启动 + 等测量跑完 + 取回结果并打印")
    ap.add_argument("--overlay", action="store_true",
                    help="悬浮窗基准：安装 + 授权 + 起前台服务 + 取回结果并打印")
    args = ap.parse_args()

    preflight()
    os.makedirs(BUILD, exist_ok=True)

    step("准备 assets")
    assets_dir = prepare_assets()

    step("aapt2 link（manifest + assets）")
    base = link_resources(assets_dir)

    step("kotlinc 编译")
    classes = compile_kotlin()

    step("d8 转 dex")
    dex_file = dex(classes)

    step("打包")
    unsigned = pack(base, dex_file)

    step("对齐 + 签名")
    ensure_keystore()
    apk = sign_and_align(unsigned)

    print("\n产物: %s" % apk)

    if args.no_install:
        return

    step("安装到设备")
    adb(["install", "-r", "-t", apk])

    if args.overlay:
        step("启动悬浮窗并采集")
        collect_overlay()
    elif args.collect:
        step("启动并采集")
        collect()
    elif args.run:
        step("启动")
        adb(["shell", "am", "start", "-n", "dpet.poc/.PetPerfActivity"])


if __name__ == "__main__":
    main()
