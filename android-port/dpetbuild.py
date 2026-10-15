#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deepseek-pet 安卓打包公共链 —— 刻意不走 Gradle。

为什么不用 Gradle / AGP
-----------------------
Gradle 发行包 + AGP + Maven 依赖在境内拉取又慢又容易断，而这个工程要的只是
"把几个 Kotlin 文件变成能装的 APK"，迭代一轮 10 秒。手工链
`aapt2 -> kotlinc -> d8 -> zipalign -> apksigner` 全程只依赖已经装好的 SDK 与 JDK。

两个 APK 共用这套：
  * `build_app.py`   —— 正式手机版（`app/`，包名 dpet.app）
  * `build_bench.py` —— 性能基准（`bench/`，包名 dpet.benchui）

同时也要认一件事：**这套链有它做不到的事**。要写 Compose、要用 AndroidX、
要资源系统（布局/图标/多语言），就该换成 Gradle —— 手工链没有资源编译器，
`res/` 目录得自己拼二进制，不值得。这也是为什么界面全用代码构建。
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)                       # deepseek-pet/

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

DEFAULT_KEYSTORE = os.path.join(HERE, "debug.keystore")

# kotlinc 的压缩包。**本机下不到**（境内拿不到 kotlin-compiler 的直链），
# 所以它是唯一火种：解压目录 `tools/kotlinc/`（93 MB）可以随便删，
# 这个 zip（86 MB）不能 —— 见 ensure_kotlinc()。
KOTLIN_ZIP = os.path.join(HERE, "tools", "kotlin-compiler-2.4.20.zip")


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


def ensure_kotlinc():
    """kotlinc 没解压就从同目录的 zip 里解出来。

    解压目录 93 MB、压缩包 86 MB，两个都留着纯属浪费，而压缩包**本机下不到**
    （境内拿不到 kotlin-compiler 的直链），所以 zip 必须留、目录可以删。
    解压一次十几秒 —— 与其在"省 93 MB"和"每次手动敲解压命令"之间二选一，
    不如让这一步自动：删了目录，下次构建自己补回来。
    """
    if os.path.exists(KOTLINC) and os.path.exists(KOTLIN_STDLIB):
        return
    if not os.path.exists(KOTLIN_ZIP):
        print("kotlinc 未解压，而且找不到压缩包：\n  %s\n"
              "本机下不到这个包，得从别处拷一份放进 tools/。" % KOTLIN_ZIP)
        sys.exit(1)
    step("解压 kotlinc（首次构建，或解压目录被删过）")
    with zipfile.ZipFile(KOTLIN_ZIP) as z:
        z.extractall(os.path.join(HERE, "tools"))
    if not (os.path.exists(KOTLINC) and os.path.exists(KOTLIN_STDLIB)):
        print("解压完了还是找不到 kotlinc，检查 zip 结构"
              "（顶层应该直接是 kotlinc/）：\n  %s" % KOTLIN_ZIP)
        sys.exit(1)
    log("kotlinc 就绪 —— 这个解压目录可以随时删，下次会自动重建")


def preflight(extra=()):
    """缺什么一次全列出来，别让用户在"改一行→重跑→再报缺一个"里循环。"""
    ensure_kotlinc()
    need = [PLATFORM_JAR, AAPT2, D8, ZIPALIGN, APKSIGNER, KOTLINC, KOTLIN_STDLIB,
            os.path.join(JDK, "bin", "java.exe")]
    need += list(extra)
    missing = [p for p in need if not os.path.exists(p)]
    if missing:
        print("缺少构建依赖：")
        for m in missing:
            print("  - %s" % m)
        sys.exit(1)


# ---------------------------------------------------------------- 打包各步

def link_resources(manifest, assets_dir, out_apk, min_sdk, target_sdk,
                   version_code, version_name):
    if os.path.exists(out_apk):
        os.remove(out_apk)
    cmd = [AAPT2, "link",
           "-I", PLATFORM_JAR,
           "--manifest", manifest,
           "--min-sdk-version", str(min_sdk),
           "--target-sdk-version", str(target_sdk),
           "--version-code", str(version_code),
           "--version-name", str(version_name),
           "-o", out_apk]
    if assets_dir:
        cmd += ["-A", assets_dir]
    run(cmd)
    log("base.apk = %.1f KB" % (os.path.getsize(out_apk) / 1024.0))
    return out_apk


def compile_kotlin(src_dirs, classes_dir, jvm_target="17"):
    if os.path.isdir(classes_dir):
        shutil.rmtree(classes_dir)
    os.makedirs(classes_dir)

    srcs = []
    for d in src_dirs:
        srcs += sorted(glob.glob(os.path.join(d, "**", "*.kt"), recursive=True))
    if not srcs:
        print("没找到 Kotlin 源文件：%s" % ", ".join(src_dirs))
        sys.exit(1)
    log("源文件 %d 个" % len(srcs))

    run([KOTLINC, "-classpath", PLATFORM_JAR, "-jvm-target", jvm_target,
         "-nowarn", "-d", classes_dir] + srcs)
    n = len(glob.glob(os.path.join(classes_dir, "**", "*.class"), recursive=True))
    log("编译产物 %d 个 class" % n)
    return classes_dir


def dex(classes_dir, dex_dir, min_sdk):
    if os.path.isdir(dex_dir):
        shutil.rmtree(dex_dir)
    os.makedirs(dex_dir)

    inputs = sorted(glob.glob(os.path.join(classes_dir, "**", "*.class"), recursive=True))
    inputs.append(KOTLIN_STDLIB)
    run([D8, "--lib", PLATFORM_JAR, "--min-api", str(min_sdk),
         "--output", dex_dir] + inputs)

    out = sorted(glob.glob(os.path.join(dex_dir, "classes*.dex")))
    if not out:
        print("d8 没有产出 classes.dex")
        sys.exit(1)
    total = sum(os.path.getsize(f) for f in out)
    log("dex %d 个 · 共 %.1f KB（含 kotlin-stdlib，未过 R8）"
        % (len(out), total / 1024.0))
    return out


def pack(base_apk, dex_files, out_apk):
    if os.path.exists(out_apk):
        os.remove(out_apk)
    shutil.copy2(base_apk, out_apk)
    with zipfile.ZipFile(out_apk, "a", zipfile.ZIP_DEFLATED) as z:
        for f in dex_files:
            z.write(f, os.path.basename(f))
    log("unsigned.apk = %.1f KB" % (os.path.getsize(out_apk) / 1024.0))
    return out_apk


def ensure_keystore(path=DEFAULT_KEYSTORE):
    if os.path.exists(path):
        return path
    run([KEYTOOL, "-genkeypair", "-keystore", path,
         "-alias", "androiddebugkey", "-storepass", "android",
         "-keypass", "android", "-keyalg", "RSA", "-keysize", "2048",
         "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US"])
    log("已生成调试签名 %s" % path)
    return path


def sign_and_align(unsigned_apk, out_apk, keystore=DEFAULT_KEYSTORE):
    aligned = unsigned_apk.replace("unsigned.apk", "aligned.apk")
    run([ZIPALIGN, "-f", "-p", "4", unsigned_apk, aligned])
    if os.path.exists(out_apk):
        os.remove(out_apk)
    run([APKSIGNER, "sign", "--ks", keystore,
         "--ks-pass", "pass:android", "--key-pass", "pass:android",
         "--out", out_apk, aligned])
    v = run([APKSIGNER, "verify", "--print-certs", out_apk])
    log("签名校验: %s" % (v.stdout or "").strip().splitlines()[-1])
    log("%s = %.1f KB" % (os.path.basename(out_apk), os.path.getsize(out_apk) / 1024.0))
    return out_apk


def build(*, manifest, src_dirs, assets_dir, build_dir, out_name,
          min_sdk, target_sdk, version_code, version_name, jvm_target="17"):
    """把整套链跑一遍，返回 APK 路径。"""
    os.makedirs(build_dir, exist_ok=True)
    base = os.path.join(build_dir, "base.apk")
    classes = os.path.join(build_dir, "classes")
    dex_dir = os.path.join(build_dir, "dex")
    unsigned = os.path.join(build_dir, "unsigned.apk")
    out_apk = os.path.join(build_dir, out_name)

    step("aapt2 link（manifest%s）" % (" + assets" if assets_dir else ""))
    link_resources(manifest, assets_dir, base, min_sdk, target_sdk,
                   version_code, version_name)

    step("kotlinc 编译")
    compile_kotlin(src_dirs, classes, jvm_target)

    step("d8 转 dex")
    dex_files = dex(classes, dex_dir, min_sdk)

    step("打包")
    pack(base, dex_files, unsigned)

    step("对齐 + 签名")
    ensure_keystore()
    return sign_and_align(unsigned, out_apk)


# ---------------------------------------------------------------- adb

def adb(args, check=True):
    return run([ADB] + args, check=check)


def device_serial():
    p = adb(["devices"], check=False)
    for line in (p.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return None


# ---------------------------------------------------------------- 装机
#
# 这台 Redmi Note 11（Android 17 / HyperOS）的「USB 安装」开关是关的，于是
# `adb install` / `pm install` / `install-create+commit` 三条路**全部**被静默拒绝：
#
#     Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]
#
# 设备端根本不弹框，只回这句。同名的几个 settings 键（adb_install_need_confirm、
# verifier_verify_adb_installs）都已经是"允许"状态，与它无关 —— 那是另一个开关，
# 只能由人在「开发者选项 → USB 安装」里打开（还要登录小米账号 + 插卡）。
#
# 绕法：把它当成"用户手动装 APK"。`adb push` 到 Download 再用
# `am start -a INSTALL_PACKAGE` 唤起系统安装器 —— 那条链路不受 USB 安装策略管辖，
# 只需要有人点一下「继续」。这里连那一下也自动化掉（uiautomator dump 取按钮坐标 + input tap）。
#
# 这条路留下的副作用是必须的：正式包**不开 debuggable**，所以之后想读日志
# 得靠应用自己写到 `Android/data/<pkg>/files/` 里的文件（见 DLog.kt）。

INSTALL_BUTTON_TEXTS = ("继续", "安装", "继续安装", "仍然安装", "确定", "允许")


def _ui_tap(texts, build_dir, extra_candidates=()):
    """在设备当前界面上找这些文字的控件并点它。返回是否点到了。"""
    B_dump = "/sdcard/dpet-ui.xml"
    local = os.path.join(build_dir, "ui-dump.xml")
    adb(["shell", "uiautomator", "dump", B_dump], check=False)
    if os.path.exists(local):
        os.remove(local)
    adb(["pull", B_dump, local], check=False)
    if not os.path.exists(local):
        return False

    with open(local, encoding="utf-8", errors="replace") as f:
        xml = f.read()

    for text in list(texts) + list(extra_candidates):
        m = re.search(
            r'text="%s"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"' % re.escape(text),
            xml)
        if not m:
            continue
        x1, y1, x2, y2 = (int(g) for g in m.groups())
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        log("点击「%s」 @ (%d,%d)" % (text, cx, cy))
        adb(["shell", "input", "tap", str(cx), str(cy)], check=False)
        return True
    return False


def _last_update_time(pkg):
    p = adb(["shell", "dumpsys", "package", pkg], check=False)
    m = re.search(r"lastUpdateTime=([0-9\- :]+)", p.stdout or "")
    return m.group(1) if m else ""


def install_with_ui_fallback(apk, pkg, build_dir, rounds=3):
    """先试 adb install；被 USB 安装策略拦下就走系统安装器那条路。"""
    p = adb(["install", "-r", "-t", apk], check=False)
    out = (p.stdout or "") + (p.stderr or "")
    if "Success" in out:
        log("adb install 成功")
        return True

    if "USER_RESTRICTED" not in out and "INSTALL_FAILED" in out:
        print("安装失败（非 USB 安装限制）：\n%s" % out.strip())
        return False

    log("adb install 被 HyperOS 拦下，改走系统安装器")

    remote = "/sdcard/Download/%s" % os.path.basename(apk)
    adb(["push", apk, remote])
    before = _last_update_time(pkg)

    for i in range(rounds):
        adb(["shell", "am", "start", "-a", "android.intent.action.INSTALL_PACKAGE",
             "-d", "file://%s" % remote], check=False)
        time.sleep(3.5)
        _ui_tap(INSTALL_BUTTON_TEXTS, build_dir)
        time.sleep(4)

        after = _last_update_time(pkg)
        if after and after != before:
            log("安装成功（lastUpdateTime=%s）" % after)
            return True
        log("第 %d 轮没装上，重试" % (i + 1))

    print("安装未成功。可能是设备上弹了意料之外的确认框 —— "
          "把 APK 手动装一次即可：/sdcard/Download/%s" % os.path.basename(apk))
    return False
