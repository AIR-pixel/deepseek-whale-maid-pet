# -*- coding: utf-8 -*-
r"""打一个**自包含**便携包（zip）：把精简 Python + 精简 PyQt5 塞进 runtime/，
对方解压双击即可用，不需要先装 Python 或 pyqt5。

和 `build_package.py`（源码包 727 KB）的区别只有一个：多一个 `runtime/`。
启动器早就预留了 `if exist "%HERE%runtime\pythonw.exe"` 分支，所以**不用改一行代码**。

只装真正用到的部分，不做"整个 venv 拷进去"：
    PyQt5 完整目录 142 MB → 精简后 ~35 MB
    CPython 48 MB        → 精简后 ~21 MB
    （裁掉 pip/setuptools、include/libs、ensurepip/venv/pydoc_data/_pyrepl、
      openssl（libcrypto 7.6 MB）、sqlite3、_test* 系列、opengl32sw/ANGLE）

Qt 的 DLL 依赖不是猜的：`pe_deps()` 直接读 PE 导入表算传递闭包，
结果就是 Qt5Core/Gui/Widgets/Multimedia/Network 这 5 个（19.7 MB），没有隐藏重依赖。
VC 运行库随 Qt5/bin 一起带（msvcp140 / vcruntime140 / vcruntime140_1 / concrt140），
干净机器上不会因为缺运行库加载失败。

校验的关键一条：**用包里自带的 runtime\\python.exe 跑自检**，而不是用本机解释器。
用本机解释器跑等于什么都没验证。

用法: python tools/build_runtime.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime

import build_package as bp          # 复用素材收集与五项校验

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
sys.path.insert(0, HERE)            # pe_deps 同目录

PY_SRC = r"C:\Users\air\.workbuddy\binaries\python\versions\3.13.12"
SP_SRC = r"C:\Users\air\.workbuddy\binaries\python\envs\default\Lib\site-packages"

TOP = bp.TOP
RT = "runtime"                      # 包内 runtime/ 目录名（和启动器约定一致）

# 解释器：这些留在包内，其余目录/文件一律不拷
PY_KEEP_FILES = ("python.exe", "pythonw.exe", "python313.dll", "python3.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt")
PY_KEEP_DIRS = ("DLLs", "Lib")
PY_DROP_DIRS = {                    # 相对 PY_SRC
    "Lib/site-packages",            # 换成我们自己的精简 PyQt5
    "Lib/ensurepip", "Lib/venv", "Lib/pydoc_data", "Lib/_pyrepl",
    "Lib/idlelib", "Lib/tkinter", "Lib/test", "Lib/lib2to3", "Lib/sqlite3",
    "Scripts", "include", "libs", "tcl",
}
PY_DROP_FILES = {                   # 相对 PY_SRC
    "python3.cmd",
    "DLLs/libcrypto-3-x64.dll", "DLLs/libssl-3-x64.dll",   # openssl，7.6+1.5 MB
    "DLLs/_ssl.pyd", "DLLs/_hashlib.pyd",
    "DLLs/sqlite3.dll", "DLLs/_sqlite3.pyd",
    "DLLs/_testcapi.pyd", "DLLs/_testlimitedcapi.pyd", "DLLs/_testclinic.pyd",
    "DLLs/_testinternalcapi.pyd", "DLLs/_testbuffer.pyd",
    "DLLs/_testmultiphase.pyd", "DLLs/_testsinglephase.pyd",
    "DLLs/_testclinic_limited.pyd",
}

# PyQt5：只列真正用到的（相对 site-packages）
PYQT5_KEEP = [
    "PyQt5/__init__.py",
    "PyQt5/sip.cp313-win_amd64.pyd",
    "PyQt5/QtCore.pyd", "PyQt5/QtGui.pyd", "PyQt5/QtWidgets.pyd",
    "PyQt5/QtMultimedia.pyd", "PyQt5/_QOpenGLFunctions_2_1.pyd",
    # 不是我们直接 import 的，但 PyQt5.QtMultimedia 内部会 import 它。
    # 漏了会在 import 阶段报 No module named 'PyQt5.QtNetwork'。
    "PyQt5/QtNetwork.pyd",
    "PyQt5/Qt5/bin/Qt5Core.dll", "PyQt5/Qt5/bin/Qt5Gui.dll",
    "PyQt5/Qt5/bin/Qt5Widgets.dll", "PyQt5/Qt5/bin/Qt5Multimedia.dll",
    "PyQt5/Qt5/bin/Qt5Network.dll",
    "PyQt5/Qt5/bin/msvcp140.dll", "PyQt5/Qt5/bin/msvcp140_1.dll",
    "PyQt5/Qt5/bin/vcruntime140.dll",
    "PyQt5/Qt5/bin/vcruntime140_1.dll", "PyQt5/Qt5/bin/concrt140.dll",
    "PyQt5/Qt5/plugins/platforms/qwindows.dll",
    "PyQt5/Qt5/plugins/platforms/qoffscreen.dll",     # 只为无头自检，0.7 MB
    "PyQt5/Qt5/plugins/imageformats/qwebp.dll",       # 立绘是 webp，缺了必崩
    "PyQt5/Qt5/plugins/styles/qwindowsvistastyle.dll",
    "PyQt5/Qt5/plugins/mediaservice/dsengine.dll",
    "PyQt5/Qt5/plugins/mediaservice/qtmedia_audioengine.dll",
    "PyQt5/Qt5/plugins/mediaservice/wmfengine.dll",
    "PyQt5/Qt5/plugins/audio/qtaudio_windows.dll",
    "PyQt5/Qt5/plugins/audio/qtaudio_wasapi.dll",
]

FOOTER = """
---

> **本文件来自自包含便携包。** 解压后双击 `启动桌宠.bat` 即可，**不需要**先装
> Python 或 PyQt5 —— `runtime/` 里已经带了精简版解释器与 PyQt5。
>
> `runtime/` 是运行时的最小可用集：完整 PyQt5 目录 142 MB，这里只留了用到的
> QtCore / QtGui / QtWidgets / QtMultimedia / QtNetwork、WebP 图片插件、
> 音频后端和 Windows 平台插件。**不要删 runtime 里的文件**，也不要拿它去跑别的程序。
>
> 打包时间：{when}
"""


def sz(p):
    if os.path.isfile(p):
        return os.path.getsize(p)
    t = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return t


def copy_tree(src, dst, drop_dirs, drop_files, keep_dirs=None, keep_files=None):
    """按白名单/黑名单拷贝，返回 (文件数, 字节数, 缺失项)。"""
    missing, n, total = [], 0, 0
    for f in (keep_files or ()):
        s = os.path.join(src, f)
        if not os.path.exists(s):
            missing.append(f)
            continue
        d = os.path.join(dst, f)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        n += 1
        total += os.path.getsize(d)
    for sub in (keep_dirs or ()):
        base = os.path.join(src, sub)
        if not os.path.isdir(base):
            missing.append(sub + "/")
            continue
        for r, dirs, fs in os.walk(base):
            rel = os.path.relpath(r, src).replace("\\", "/")
            dirs[:] = [x for x in dirs
                       if rel + "/" + x not in drop_dirs and x + "/" not in drop_dirs]
            os.makedirs(os.path.join(dst, rel), exist_ok=True)
            for f in fs:
                p = rel + "/" + f
                if p in drop_files or p.startswith("Lib/site-packages/"):
                    continue
                s = os.path.join(r, f)
                d = os.path.join(dst, rel, f)
                try:
                    shutil.copy2(s, d)
                except OSError:
                    continue
                n += 1
                total += os.path.getsize(s)
    return n, total, missing


def build_stage(stage, when):
    """把整包铺到 stage/TOP/ 下，返回统计。"""
    dst = os.path.join(stage, TOP)
    os.makedirs(dst, exist_ok=True)

    # 1) 桌宠本体（与源码包同一套收集逻辑）
    items = bp.collect()
    for rel, full in items:
        out = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if full is None:
            with open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(bp.PACKAGE_CFG, ensure_ascii=False, indent=2) + "\n")
        elif rel == "README.md":
            with open(full, encoding="utf-8") as fh:
                # 与源码包同一套剥除逻辑，见 build_package.slim_readme 的说明
                body = bp.slim_readme(fh.read().replace("\r\n", "\n")).rstrip()
            with open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(body + "\n" + FOOTER.format(when=when))
        else:
            shutil.copy2(full, out)

    # 2) 精简解释器
    rtdir = os.path.join(dst, RT)
    npy, bpy, _miss = copy_tree(PY_SRC, rtdir, PY_DROP_DIRS, PY_DROP_FILES,
                                keep_dirs=PY_KEEP_DIRS, keep_files=PY_KEEP_FILES)

    # 3) 精简 PyQt5 → runtime/Lib/site-packages/PyQt5/...
    qt_missing = []
    nqt = bqt = 0
    for rel in PYQT5_KEEP:
        s = os.path.join(SP_SRC, rel.replace("/", os.sep))
        if not os.path.exists(s):
            qt_missing.append(rel)
            continue
        d = os.path.join(rtdir, "Lib", "site-packages", rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        nqt += 1
        bqt += os.path.getsize(d)

    # qwindowsvistastyle.dll 在某些版本里叫别的名字，缺了不算致命
    return {"py_files": npy, "py_bytes": bpy, "qt_files": nqt, "qt_bytes": bqt,
            "qt_missing": qt_missing, "items": items}


def verify(zip_path, ex):
    """自包含包专有校验；通用五项交给 build_package.verify，但用包内解释器跑。"""
    ok = True
    zf = zipfile.ZipFile(zip_path)
    names = set(zf.namelist())

    print("[A] 包内运行时文件齐全")
    need = [f"{RT}/pythonw.exe", f"{RT}/python.exe", f"{RT}/python313.dll",
            f"{RT}/Lib/site-packages/PyQt5/QtCore.pyd",
            f"{RT}/Lib/site-packages/PyQt5/Qt5/bin/Qt5Core.dll",
            f"{RT}/Lib/site-packages/PyQt5/Qt5/plugins/platforms/qwindows.dll",
            f"{RT}/Lib/site-packages/PyQt5/Qt5/plugins/imageformats/qwebp.dll"]
    for n in need:
        hit = f"{TOP}/{n}" in names
        ok &= hit
        print(("  OK   " if hit else "  FAIL ") + n)

    print("[B] 包内解释器能不能 import 我们用到的全部 PyQt5 模块")
    py = os.path.join(ex, RT, "python.exe")
    env = _clean_env()
    # 逐个 import 而不是只试 QtCore：PyQt5 的模块之间有隐式依赖
    # （QtMultimedia 会 import PyQt5.QtNetwork），少拷一个 .pyd 只在 import 时才炸。
    code = ("mods = ['QtCore', 'QtGui', 'QtWidgets', 'QtMultimedia']\n"
            "for m in mods:\n"
            "    __import__('PyQt5.' + m)\n"
            "from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR\n"
            "print('BUNDLED_QT', QT_VERSION_STR, PYQT_VERSION_STR, 'mods', len(mods))\n")
    r = subprocess.run([py, "-c", code], cwd=os.path.join(ex, RT), env=env,
                       capture_output=True, text=True, errors="ignore", timeout=120)
    line = next((l for l in (r.stdout or "").splitlines() if "BUNDLED_QT" in l), "")
    good = r.returncode == 0 and line
    ok &= bool(good)
    print(("  OK   " if good else "  FAIL ")
          + (line or f"rc={r.returncode} {(r.stderr or '')[-300:]}"))

    print("[C] 用包内解释器跑桌宠自检（含素材解码 / 状态机 / 音效就绪）")
    # 这一步同时是"非 ASCII 路径"的回归测试：解包目录名是中文，
    # Qt 若自己推导插件路径就会得到 '?' 然后弹错误框卡死（表现为超时）。
    saved = {k: os.environ.pop(k) for k in
             ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "QT_PLUGIN_PATH",
              "QT_QPA_PLATFORM_PLUGIN_PATH", "DPET_PYW") if k in os.environ}
    try:
        ok &= bp.verify(zip_path, py)
    except subprocess.TimeoutExpired:
        ok = False
        print("  FAIL 自检超时 —— 典型症状是 Qt 找不到平台插件、弹了模态错误框卡住")
    finally:
        os.environ.update(saved)

    print("[D] 包内无机主路径残留")
    hit = []
    for n in names:
        if n.startswith(f"{TOP}/{RT}/Lib/"):       # stdlib 上千个文件，不含我们的路径
            continue
        if not n.lower().endswith((".py", ".bat", ".json", ".md", ".txt", ".cfg", ".ini", ".pth")):
            continue
        try:
            data = zf.read(n).decode("utf-8", "ignore")
        except Exception:
            continue
        for pat in ("Users\\air", "Users/air", ".workbuddy", "envs\\default", "envs/default"):
            if pat in data:
                hit.append(f"{n} ~ {pat}")
    ok &= not hit
    print(("  OK   " if not hit else "  FAIL ") + (str(hit) if hit else "无"))

    print("[E] 精简 Qt 清单是否覆盖 PE 硬依赖闭包")
    ok &= _check_qt_closure()
    zf.close()
    return ok


def _check_qt_closure():
    """解析 PE 导入表算 Qt 的硬依赖闭包，和 PYQT5_KEEP 对比。

    手写白名单漏一个 DLL，症状是"在别人机器上启动即挂且没有报错"——人眼很难发现。
    这里让机器来查。
    """
    from pe_deps import closure
    bin_dir = os.path.join(SP_SRC, "PyQt5", "Qt5", "bin")
    if not os.path.isdir(bin_dir):
        print("  --   跳过（本机没有 PyQt5，无法算闭包）")
        return True
    seeds = [os.path.join(SP_SRC, "PyQt5", x) for x in
             ("QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtMultimedia.pyd",
              "QtNetwork.pyd")]
    seeds += [os.path.join(bin_dir, f) for f in
              ("Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll", "Qt5Multimedia.dll",
               "Qt5Network.dll")]
    seeds += [os.path.join(SP_SRC, r.replace("/", os.sep)) for r in PYQT5_KEEP
              if r.endswith(".dll")]
    needed, missing = closure(seeds, bin_dir)
    kept = {os.path.basename(r).lower() for r in PYQT5_KEEP}
    gap = sorted(needed - kept)
    ok = not gap and not missing
    msg = f"闭包 {len(needed)} 个 DLL"
    if gap:
        msg += f"  清单漏了: {gap}"
    if missing:
        msg += f"  非系统又找不到: {sorted(missing)}"
    print(("  OK   " if ok else "  FAIL ") + msg)
    return ok


def _clean_env():
    """跑包内解释器时必须清掉会串环境的变量，否则自检可能在用本机的包。"""
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "QT_PLUGIN_PATH",
              "QT_QPA_PLATFORM_PLUGIN_PATH", "DPET_PYW"):
        env.pop(k, None)
    return env


def main():
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp = datetime.now().strftime("%Y%m%d")
    zip_path = os.path.join(DIST, f"{TOP}_自包含_{stamp}.zip")
    os.makedirs(DIST, exist_ok=True)

    if not os.path.isdir(PY_SRC):
        print(f"找不到解释器目录: {PY_SRC}")
        return 1

    stage = tempfile.mkdtemp(prefix="dpet_rt_")
    try:
        print(f"铺开运行时 → {stage}")
        st = build_stage(stage, when)
        raw = sz(os.path.join(stage, TOP))
        print(f"  解释器 {st['py_files']} 文件 / {st['py_bytes'] / 1048576:.1f} MB")
        print(f"  PyQt5  {st['qt_files']} 文件 / {st['qt_bytes'] / 1048576:.1f} MB")
        print(f"  整包解压后 {raw / 1048576:.1f} MB")
        if st["qt_missing"]:
            print("  ! PyQt5 清单里缺失（可能版本差异）: " + ", ".join(st["qt_missing"]))

        print(f"\n压缩 → {zip_path}")
        base = os.path.dirname(zip_path)
        tmp_zip = zip_path + ".part"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for r, dirs, fs in os.walk(os.path.join(stage, TOP)):
                for f in sorted(fs):
                    full = os.path.join(r, f)
                    arc = os.path.relpath(full, stage).replace("\\", "/")
                    z.write(full, arc)
        os.replace(tmp_zip, zip_path)
        size = os.path.getsize(zip_path)
        print(f"  {size / 1048576:.1f} MB")

        ex = os.path.join(stage, TOP)
        ok = verify(zip_path, ex)
        print()
        if ok:
            print(f"== 自包含包完成: {zip_path} ({size / 1048576:.1f} MB) ==")
        else:
            print("== 校验未通过，包不可用 ==")
        return 0 if ok else 1
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
