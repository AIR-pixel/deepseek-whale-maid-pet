# -*- coding: utf-8 -*-
"""便携包验收：解包 → 用包里自带的启动器真的跑起来 → 确认窗口出现。

比"看文件都在"强得多：一次性验证了
  * 解压后路径无关（启动器用 %~dp0，不依赖原目录）
  * 启动器在 cmd 下解析正常（纯 ASCII + CRLF 真的没问题，含 %%i 循环与 py -3 回退）
  * 素材、音效、代码在包外位置都能加载
  * 窗口真的建起来、尺寸/位置合理

两个踩过的坑：
  1) 启动器里 `start ""` 会派生一个脱离的桌宠进程，它**继承管道句柄**，
     所以 subprocess 不能 capture_output —— 否则会一直等 EOF 直到桌宠退出。
     必须 DEVNULL + 超时，然后轮询窗口。
  2) 失败分支末尾有 `pause`。stdin 必须是 DEVNULL，否则子进程会等输入把验收卡死。

解释器怎么选：包里不含 Python，启动器会在 PATH 上找 pythonw / python。
本机这两个都没有 PyQt5（PyQt5 只装在隔离 venv 里），所以验收通过 **DPET_PYW**
环境变量显式指定解释器 —— 这也顺带验证了启动器的覆盖分支是通的。

用法: python tools/accept_package.py [zip 路径] [--pyw 解释器路径]
"""
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

u32 = ctypes.WinDLL("user32", use_last_error=True)
u32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u32.GetWindowTextLengthW.argtypes = [wt.HWND]
u32.IsWindowVisible.argtypes = [wt.HWND]
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

TITLE = "DeepSeek 鲸鱼娘"
DEVNULL = subprocess.DEVNULL


def windows(title=TITLE):
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n > 0:
                b = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, b, n + 1)
                if title in b.value:
                    hits.append(h)
        return True

    u32.EnumWindows(cb, 0)
    return hits


def can_import(pyw, mod="PyQt5"):
    """这个解释器能不能 import 指定模块。"""
    try:
        r = subprocess.run([pyw, "-c", "import " + mod],
                           stdout=DEVNULL, stderr=DEVNULL, timeout=30,
                           stdin=DEVNULL)
        return r.returncode == 0
    except Exception:
        return False


def pick_pyw(explicit):
    """挑一个装了 PyQt5 的解释器。explicit 优先。"""
    cands = []
    if explicit:
        cands.append(explicit)
    env_pyw = os.environ.get("DPET_PYW")
    if env_pyw:
        cands.append(env_pyw)
    # 开发机上装了 PyQt5 的是隔离 venv；PATH 上的 pythonw 通常没装
    cands.append(r"C:\Users\air\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe")
    for c in (shutil.which("pythonw"), shutil.which("python")):
        if c:
            cands.append(c)
    for c in cands:
        if c and os.path.exists(c) and can_import(c):
            return c
    return None


def _rmtree_retry(path, tries=12, delay=0.25):
    """删解包目录，带重试。

    `taskkill` 返回 0 **不代表进程已经退出**，它还没死透时解包目录里的文件仍被占用，
    `rmtree(ignore_errors=True)` 会**静默留下一整棵目录树**（在 %TEMP% 里悄悄堆积）。
    所以这里重试并回报结果，而不是假装成功。
    """
    for _ in range(tries):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(delay)
    return not os.path.exists(path)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    dist = os.path.join(root, "dist")

    argv = sys.argv[1:]
    explicit = None
    if "--pyw" in argv:
        i = argv.index("--pyw")
        explicit = argv[i + 1]
        del argv[i:i + 2]
    if argv:
        zip_path = argv[0]
    else:
        cands = [os.path.join(dist, f) for f in os.listdir(dist)] if os.path.isdir(dist) else []
        cands = [c for c in cands if c.endswith(".zip")]
        if not cands:
            print("dist 下没有 zip，先跑 tools/build_package.py")
            return 1
        zip_path = max(cands, key=os.path.getmtime)

    pyw = pick_pyw(explicit)
    force_override = ("--use-override" in argv) or (explicit is not None)

    print(f"[i] 验收 {os.path.basename(zip_path)}")
    tmp = tempfile.mkdtemp(prefix="dpet_accept_")
    pet_pid = None
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        top = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
        if len(top) != 1:
            print(f"  FAIL 顶层目录不唯一: {top}")
            return 1
        ex = os.path.join(tmp, top[0])
        nfiles = sum(len(f) for _, _, f in os.walk(ex))
        print(f"[1] 解包到 {ex}（{nfiles} 个文件）")
        # 解包路径带中文顶层目录 —— 正好当"非 ASCII 路径"的回归测试
        print(f"    路径含非 ASCII: {any(ord(c) > 127 for c in ex)}")

        before = set(windows())
        if before:
            print(f"    注意：已有 {len(before)} 个同名窗口（你自己的实例），只认新出现的")

        # 用包里自带的启动器启动 —— 顺带验证 bat 的编码/CRLF/相对路径/ %%i 循环
        env = dict(os.environ)
        # 包里自带 runtime/ 时**必须**让它用自己的解释器：注入 DPET_PYW 会覆盖掉
        # runtime 分支，变成"用本机 PyQt5 测了一遍"，包内运行时压根没被验证。
        if os.path.exists(os.path.join(ex, "runtime", "pythonw.exe")) and not force_override:
            env.pop("DPET_PYW", None)
            print("[i] 包内自带 runtime/ → 走包内解释器（不注入 DPET_PYW）")
        else:
            if not pyw:
                print("FAIL 找不到装了 PyQt5 的解释器；用 --pyw 指定，或先 pip install pyqt5")
                return 1
            env["DPET_PYW"] = pyw
            print(f"[i] 无内置运行时 → 注入 DPET_PYW = {pyw}")
        p = subprocess.run(["cmd", "/c", "启动桌宠.bat"], cwd=ex, env=env,
                           stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                           timeout=30)
        print(f"[2] 启动器返回码 {p.returncode}")
        if p.returncode != 0:
            print("  FAIL 启动器非 0 退出（落到了 nopython / nopyqt / pause）")
            return 1

        hwnd = None
        for _ in range(48):
            time.sleep(0.25)
            new = set(windows()) - before
            if new:
                hwnd = sorted(new)[0]
                break
        if not hwnd:
            print("  FAIL 启动器返回了，但桌宠窗口没出现")
            return 1

        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pet_pid = pid.value
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w < 60 or h < 60:
            print(f"  FAIL 窗口尺寸异常 {w}x{h}")
            return 1
        print(f"[3] PASS 窗口出现 pid={pet_pid} 尺寸={w}x{h} 位置=({r.left},{r.top})")
        time.sleep(1.2)
        # 再确认它没有秒退
        if not (set(windows()) & {hwnd}):
            print("  FAIL 窗口出现后又消失了（启动即崩）")
            return 1
        print("== 便携包可独立运行 ==")
        return 0
    finally:
        if pet_pid:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pet_pid)],
                           stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)
            print("[i] 已关闭验收实例")
        if not _rmtree_retry(tmp):
            print(f"[!] 解包目录没删干净（文件被占用），需手动清理: {tmp}")


if __name__ == "__main__":
    sys.exit(main())
