#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建正式手机版 APK（包名 dpet.app）。

用法：
    python build_app.py                # 构建 + 安装到已连接设备
    python build_app.py --no-install   # 只构建
    python build_app.py --run          # 构建 + 安装 + 启动控制面板
    python build_app.py --log          # 跟一段 logcat 看启动过程
    python build_app.py --assets-only  # 只把 assets 准备好（排查内容包问题时用）

内容包（assets）由 `prepare_assets` 现拼：`content/actions.json` + `assets/pet/*.webp`
+ `assets/sfx/*.wav`。桌面端的 `assets/pet/manifest.json` 不进包 ——
它是给发布流程核对素材用的，运行时不需要。
"""

import argparse
import glob
import os
import shutil
import sys
import time

import dpetbuild as B

HERE = B.HERE
PROJ = B.PROJ

APP = os.path.join(HERE, "app")
BUILD = os.path.join(APP, "build")
MANIFEST = os.path.join(APP, "AndroidManifest.xml")
SRC_DIRS = [os.path.join(HERE, "core"), os.path.join(APP, "src")]

MIN_SDK = "26"
TARGET_SDK = "37"
PKG = "dpet.app"


def prepare_assets():
    """把 content/ + assets/pet/ + assets/sfx/ 拼进 build/assets，作为 APK 的 assets。"""
    dst = os.path.join(BUILD, "assets")
    if os.path.isdir(dst):
        shutil.rmtree(dst)

    os.makedirs(os.path.join(dst, "content"))
    shutil.copy2(os.path.join(PROJ, "content", "actions.json"),
                 os.path.join(dst, "content", "actions.json"))

    n_pet = 0
    pet_dst = os.path.join(dst, "pet")
    os.makedirs(pet_dst)
    for f in sorted(glob.glob(os.path.join(PROJ, "assets", "pet", "*.webp"))):
        shutil.copy2(f, os.path.join(pet_dst, os.path.basename(f)))
        n_pet += 1

    n_sfx = 0
    sfx_dst = os.path.join(dst, "sfx")
    os.makedirs(sfx_dst)
    for f in sorted(glob.glob(os.path.join(PROJ, "assets", "sfx", "*.wav"))):
        shutil.copy2(f, os.path.join(sfx_dst, os.path.basename(f)))
        n_sfx += 1

    B.log("assets: actions.json + %d 张立绘 + %d 条音效" % (n_pet, n_sfx))
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--run", action="store_true", help="装上后直接打开控制面板")
    ap.add_argument("--log", action="store_true", help="装完跟 12 秒 logcat")
    ap.add_argument("--assets-only", action="store_true")
    args = ap.parse_args()

    B.preflight()
    os.makedirs(BUILD, exist_ok=True)

    B.step("准备 assets")
    assets = prepare_assets()
    if args.assets_only:
        return

    apk = B.build(
        manifest=MANIFEST,
        src_dirs=SRC_DIRS,
        assets_dir=assets,
        build_dir=BUILD,
        out_name="pet.apk",
        min_sdk=MIN_SDK,
        target_sdk=TARGET_SDK,
        version_code=20000,
        version_name="2.0.0",
    )
    print("\n产物: %s" % apk)

    if args.no_install:
        return

    if B.device_serial() is None:
        print("\n没有检测到设备（adb devices 为空），跳过安装。")
        return

    B.step("安装到设备")
    if not B.install_with_ui_fallback(apk, PKG, BUILD):
        return

    # 重装会把受控权限重置回"未授予"（`appops set` 的记录跟着包一起被清掉），
    # 每轮迭代都要重新开一次太蠢 —— 这是开发脚本，顺手代劳。
    # 正式分发给别人时对方仍然要在系统设置里自己点。
    B.adb(["shell", "appops", "set", PKG, "SYSTEM_ALERT_WINDOW", "allow"], check=False)
    B.adb(["shell", "pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS"], check=False)
    B.log("已重新授予悬浮窗与通知权限")

    if args.run:
        B.step("启动控制面板")
        B.adb(["shell", "am", "start", "-n", "%s/.MainActivity" % PKG])

    if args.log:
        B.step("抓取启动日志（12 秒）")
        B.adb(["logcat", "-c"], check=False)
        B.adb(["shell", "am", "start", "-n", "%s/.MainActivity" % PKG], check=False)
        time.sleep(12)
        p = B.adb(["logcat", "-d", "-s", "PETAPP:V", "PETSFX:V",
                   "AndroidRuntime:E"], check=False)
        print((p.stdout or "")[-8000:])


if __name__ == "__main__":
    main()
