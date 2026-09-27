# -*- coding: utf-8 -*-
"""打一个源码便携包（zip）+ 自检。

只装"运行桌宠真正需要的东西"：
    src/ · assets/ · content/ · config.json · 启动桌宠.bat · README.md

不进包：预览图（preview_*.png/gif）、原始素材（ref_assets/）、开发工具（tools/）。

config.json 用**默认值**而不是本机那份——里面存着窗口坐标，
带到别的机器上虽然启动时会夹回屏幕内，但从默认的右下角开始更自然。

打完立刻做六项校验（都是踩过的坑，所以固化下来）：
    1. 必需文件齐全
    2. 内容包声明的素材齐全、状态引用的帧都有定义
    3. 启动器仍是纯 ASCII + CRLF（zip 往返不该改变它，但不验证不放心）
    4. 包内 config.json 不带本机窗口坐标
    5. 解包出来的副本能真的加载素材、切状态、就绪音效
    6. 远端清单（content/manifest.json）与包内文件哈希一致

用法: python tools/build_package.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")

TOP = "DeepSeek鲸鱼娘桌宠"          # zip 内的顶层目录
INCLUDE_DIRS = ("src", "assets", "content")
INCLUDE_FILES = ("启动桌宠.bat", "README.md")
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_EXT = {".pyc", ".pyo"}

# 便携包里的 config.json：全用默认值，不带本机窗口坐标。
# 刻意不带 update_consent —— 首次启动时跟用户打一次招呼再联网。
PACKAGE_CFG = {
    "x": None, "y": None,
    "height": 280,
    "opacity": 1.0,
    "on_top": True,
    "bubble": True,
    "remind_water": False,
    "remind_sit": False,
    "mute_speech": False,
    "sfx": True,
    "sfx_volume": 0.6,
    "auto_update": True,
}

FOOTER = """
---

> **本文件来自源码便携包。** 包里只有运行所需的 `src/` 与 `assets/`
> （立绘 + 音效）、`config.json`、`启动桌宠.bat` 和这份说明。
> `tools/`（素材流水线、音效合成、测试、预览脚本）、预览图与原始素材
> `ref_assets/` 未收入——需要它们请使用开发目录版本。
>
> 打包时间：{when}
"""

# README 里只在 GitHub 上显示的那一段（横幅 / 截图 / 下载指引）的边界标记。
# 那段引用了 docs/ 下的图，而便携包里没有 docs/ —— 不剥的话解压出来的
# README 会挂一排破图。
GH_START = "<!-- GH-ONLY:START"
GH_END = "<!-- GH-ONLY:END -->"


def slim_readme(text):
    """剥掉 GH-ONLY 区间（含标记本身）。

    用显式标记而不是正则去猜"哪几行是图"：以后往 README 里加内容时，
    不会被误伤，也不会因为标记丢了就默默删正文——找不到成对标记就原样返回，
    宁可留几张破图。
    """
    a = text.find(GH_START)
    if a < 0:
        return text
    b = text.find(GH_END, a)
    if b < 0:
        return text
    return (text[:a].rstrip() + "\n" + text[b + len(GH_END):].lstrip("\n")).strip() + "\n"


def should_skip(path):
    parts = set(path.replace("\\", "/").split("/"))
    if parts & SKIP_DIRS:
        return True
    return os.path.splitext(path)[1].lower() in SKIP_EXT


def collect():
    """返回 [(zip 内相对路径, 绝对路径 或 None)]，None 表示内容由脚本生成。"""
    items = []
    for d in INCLUDE_DIRS:
        base = os.path.join(ROOT, d)
        for r, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in sorted(files):
                full = os.path.join(r, f)
                rel = os.path.relpath(full, ROOT)
                if not should_skip(rel):
                    items.append((rel.replace("\\", "/"), full))
    for f in INCLUDE_FILES:
        full = os.path.join(ROOT, f)
        if os.path.exists(full):
            items.append((f, full))
        else:
            print(f"  ! 缺少 {f}，跳过")
    items.append(("config.json", None))
    return sorted(items)


def build(zip_path, when):
    items = collect()
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, full in items:
            name = f"{TOP}/{rel}"
            if full is None:                       # 生成的 config.json
                z.writestr(name, json.dumps(PACKAGE_CFG, ensure_ascii=False, indent=2) + "\n")
            elif rel == "README.md":
                with open(full, encoding="utf-8") as fh:
                    body = slim_readme(fh.read().replace("\r\n", "\n"))
                z.writestr(name, body.rstrip() + "\n" + FOOTER.format(when=when))
            else:
                z.write(full, name)
    return items


# ------------------------------------------------------------------ 校验

def verify(zip_path, py):
    ok = True
    zf = zipfile.ZipFile(zip_path)
    names = set(zf.namelist())

    print("\n[1] 必需文件")
    need = ["src/deepseek_pet.py", "src/motion.py", "src/sfx.py", "src/lines.py",
            "src/contentpack.py", "src/updater.py",
            "content/actions.json", "content/manifest.json",
            "assets/pet/manifest.json", "config.json", "启动桌宠.bat", "README.md"]
    for n in need:
        hit = f"{TOP}/{n}" in names
        ok &= hit
        print(("  OK   " if hit else "  FAIL ") + n)

    print("[1b] README 已剥掉 GitHub 专属段")
    rd = zf.read(f"{TOP}/README.md").decode("utf-8")
    # 只查"图片引用"形态的行。项目结构树里也有 `docs/` 字样，那是文字描述，
    # 不该判失败——判据要精确到"会被渲染成图"的写法。
    dead = [ln for ln in rd.splitlines() if "docs/" in ln and ("![" in ln or "<img" in ln)]
    good = not dead and "GH-ONLY" not in rd
    ok &= good
    print(("  OK   " if good else "  FAIL ")
          + (f"{len(rd)} 字符，无 docs/ 死链" if good else f"残留: {dead[:2]}"))

    print("[2] 内容包与素材")
    # 以 content/actions.json 为准 —— 运行时读的是它。
    # assets/pet/manifest.json 只是素材流水线的产物记录，程序不再读。
    with open(os.path.join(ROOT, "content", "actions.json"), encoding="utf-8") as f:
        acts = json.load(f)
    declared = acts.get("assets") or {}
    miss = []
    for nm, meta in declared.items():
        rel = str(meta.get("file") or "").replace("\\", "/")
        if not any(c in names for c in (f"{TOP}/content/{rel}", f"{TOP}/assets/{rel}")):
            miss.append(f"{nm}({rel})")
    ok &= not miss
    print(("  OK   " if not miss else "  FAIL ")
          + f"{len(declared)} 张声明素材" + (f" 缺: {miss}" if miss else ""))

    dangling = []
    for st, smeta in (acts.get("states") or {}).items():
        for fr in smeta.get("frames") or []:
            if fr not in declared:
                dangling.append(f"{st}->{fr}")
    ok &= not dangling
    print(("  OK   " if not dangling else "  FAIL ")
          + f"{len(acts.get('states') or {})} 个状态引用的帧都有定义"
          + (f" 悬空: {dangling}" if dangling else ""))

    n_wav = sum(1 for n in names if n.startswith(f"{TOP}/assets/sfx/") and n.endswith(".wav"))
    ok &= n_wav > 0
    print(("  OK   " if n_wav else "  FAIL ") + f"{n_wav} 条音效")

    print("[3] 启动器纯 ASCII + CRLF")
    raw = zf.read(f"{TOP}/启动桌宠.bat")
    crlf = raw.count(b"\r\n")
    bare_lf = raw.count(b"\n") - crlf
    try:
        raw.decode("ascii")
        ascii_ok = True
    except UnicodeDecodeError:
        ascii_ok = False
    good = ascii_ok and bare_lf == 0
    ok &= good
    print(("  OK   " if good else "  FAIL ")
          + f"{len(raw)} 字节 / {crlf} CRLF / {bare_lf} 裸 LF / "
          + ("纯 ASCII" if ascii_ok else "含非 ASCII"))

    print("[4] 包内 config.json 不含本机坐标")
    cfg = json.loads(zf.read(f"{TOP}/config.json").decode("utf-8"))
    good = cfg.get("x") is None and cfg.get("y") is None
    ok &= good
    print(("  OK   " if good else "  FAIL ") + f"x={cfg.get('x')} y={cfg.get('y')} height={cfg.get('height')}")
    zf.close()

    print("[5] 解包后跑一遍自检")
    tmp = tempfile.mkdtemp(prefix="dpet_pkg_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        ex = os.path.join(tmp, TOP)
        # 便携包不含 tools/，所以内联一份最小自检：能加载全部素材 + 状态机可跑 + 音效就绪
        code = (
            "import os,sys,tempfile\n"
            "ex = r'%s'\n"
            "sys.path.insert(0, os.path.join(ex,'src'))\n"
            "os.environ['QT_QPA_PLATFORM']='offscreen'\n"
            # 自检不能真的联网，也不能读本机已装的远端内容
            "os.environ['DPET_USER_CONTENT']=os.path.join(tempfile.gettempdir(),'dpet_pkg_nocontent')\n"
            "from PyQt5.QtWidgets import QApplication\n"
            "import deepseek_pet as dp\n"
            "dp.CONFIG_PATH = os.path.join(tempfile.gettempdir(),'dpet_pkg_check.json')\n"
            "app = QApplication([])\n"
            "cfg = dp.load_cfg()\n"
            "cfg['auto_update'] = False\n"
            "pet = dp.PetWindow(cfg)\n"
            "pet.show()\n"
            "assert len(pet.pix) == 10, sorted(pet.pix)\n"
            "assert pet.pack.source == 'builtin', pet.pack.source\n"
            "assert len(pet.STATES) == 8, sorted(pet.STATES)\n"
            "assert pet.pack.motion_set().unknown == [], pet.pack.motion_set().unknown\n"
            "for st in pet.STATES:\n"
            "    pet._set_state(st, force=True)\n"
            "ready = pet.sfx.wait_ready()\n"
            "assert pet.sfx.ok and ready > 0, 'sfx: ' + pet.sfx.reason\n"
            "pet._tick()\n"
            "print('OFFSCREEN_OK frames=%%d states=%%d sfx=%%d win=%%dx%%d' %% (len(pet.pix), len(pet.STATES), ready, pet.win_w, pet.win_h))\n"
            "import os as _os\n"
            "_os.path.exists(dp.CONFIG_PATH) and _os.remove(dp.CONFIG_PATH)\n"
        ) % ex
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           errors="ignore", timeout=180)
        out = (r.stdout or "").strip().splitlines()
        good = r.returncode == 0 and any("OFFSCREEN_OK" in ln for ln in out)
        ok &= good
        print(("  OK   " if good else "  FAIL ")
              + (next((ln for ln in out if "OFFSCREEN_OK" in ln), "无输出")))
        if not good:
            print("  stdout:", (r.stdout or "")[-600:])
            print("  stderr:", (r.stderr or "")[-600:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("[6] 远端清单与包内文件一致")
    bad, mf = [], {}
    try:
        with open(os.path.join(ROOT, "content", "manifest.json"), encoding="utf-8") as f:
            mf = json.load(f)
        with zipfile.ZipFile(zip_path) as z:
            for rel, meta in (mf.get("files") or {}).items():
                name = f"{TOP}/content/{rel}"
                if name not in names:
                    bad.append(f"{rel} 不在包里")
                    continue
                if hashlib.sha256(z.read(name)).hexdigest() != meta.get("sha256"):
                    bad.append(f"{rel} 哈希不符")
    except Exception as e:                      # noqa: BLE001
        bad.append(str(e))
    ok &= not bad
    print(("  OK   " if not bad else "  FAIL ")
          + f"清单 r{mf.get('content_version')} 覆盖 {len(mf.get('files') or {})} 个文件"
          + (f" | {bad[:3]}" if bad else ""))
    return ok


def main():
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp = datetime.now().strftime("%Y%m%d")
    zip_path = os.path.join(DIST, f"{TOP}_{stamp}.zip")
    py = sys.executable

    print(f"打包 → {zip_path}")
    items = build(zip_path, when)
    raw = sum(os.path.getsize(f) for _, f in items if f)
    size = os.path.getsize(zip_path)
    print(f"  {len(items)} 个条目 / 原始 {raw / 1024:.0f} KB / 压缩后 {size / 1024:.0f} KB")

    ok = verify(zip_path, py)
    print()
    if ok:
        print(f"== 打包完成: {zip_path} ({size / 1024:.0f} KB) ==")
    else:
        print("== 校验未通过，包不可用 ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
