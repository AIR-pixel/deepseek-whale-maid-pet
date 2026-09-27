# -*- coding: utf-8 -*-
"""真机验证：启动桌宠 -> 按窗口句柄直接截图 -> 帧间比对 -> 收工。

不猜坐标系：用 EnumWindows 拿到窗口 HWND，再 PrintWindow 抓它自己。
PW_RENDERFULLCONTENT(=2) 才能抓到分层/半透明窗口的内容。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import tempfile
import time

# 必须在任何 GUI 相关调用之前声明 DPI 感知，否则本进程拿到的是被虚拟化的坐标
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRCDIR = os.path.join(ROOT, "src")
SRC = os.path.join(SRCDIR, "deepseek_pet.py")
PY = sys.executable
TITLE = "DeepSeek 鲸鱼娘"

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)

u32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u32.IsWindowVisible.argtypes = [wt.HWND]
u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
u32.GetWindowTextLengthW.argtypes = [wt.HWND]
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]

g32.CreateCompatibleDC.argtypes = [wt.HDC]
g32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
g32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
g32.DeleteObject.argtypes = [wt.HGDIOBJ]
g32.DeleteDC.argtypes = [wt.HDC]

BI_RGB = 0
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def find_windows(title):
    """返回所有标题匹配的可见窗口句柄。

    不能只按标题取第一个：用户自己可能正开着一个桌宠，会抓到他的窗口。
    也不能按 PID 过滤：venv 的 Scripts/python.exe 会再起一个子进程持有窗口，
    父进程 PID 和窗口 PID 不一致。用「启动前后集合做差」最稳。
    """
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd):
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        if title in buf.value:
            hits.append(hwnd)
        return True

    u32.EnumWindows(cb, 0)
    return hits


def window_rect(hwnd):
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.right - r.left, r.bottom - r.top, r.left, r.top)


def pid_of(hwnd):
    owner = wt.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    return owner.value


def grab(hwnd):
    """抓窗口内容，返回 (PIL RGB Image, (w,h), alpha 非零像素占比)"""
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None, (0, 0), 0.0

    hdc = u32.GetWindowDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    old = g32.SelectObject(mem, bmp)

    # 2 = PW_RENDERFULLCONTENT，分层窗口必须带这个标志
    ok = u32.PrintWindow(hwnd, mem, 2)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h          # 负值 = 自上而下
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    g32.SelectObject(mem, old)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(hwnd, hdc)

    raw = buf.raw
    img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
    a = img.getchannel("A")
    hist = a.histogram()
    nonzero = sum(hist[8:]) / float(w * h)
    return img.convert("RGB"), (w, h), nonzero


def diff_ratio(a, b):
    if a is None or b is None or a.size != b.size:
        return -1.0
    pa, pb = a.tobytes(), b.tobytes()
    n = len(pa) // 3
    changed = 0
    for i in range(0, len(pa), 3):
        if abs(pa[i] - pb[i]) > 8 or abs(pa[i + 1] - pb[i + 1]) > 8 or abs(pa[i + 2] - pb[i + 2]) > 8:
            changed += 1
    return changed / float(n)


def main():
    # 可选：python tools/verify_live.py --height 80
    # 用一张临时配置起进程，绝不碰你自己的 config.json
    height = None
    argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "--height":
        height = int(argv[1])

    tmp_cfg = os.path.join(tempfile.gettempdir(), "deepseek_pet_verify_cfg.json")
    if height is None:
        boot = ("import sys; sys.path.insert(0, r'%s'); "
                "import deepseek_pet as dp; sys.exit(dp.main())") % SRCDIR
        print(f"[i] 解释器: {PY}（沿用现有配置）")
    else:
        seed = {}
        try:
            with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
                seed = json.load(f)
        except Exception:
            pass
        seed["height"] = height
        seed["x"], seed["y"] = 400, 400
        with open(tmp_cfg, "w", encoding="utf-8") as f:
            json.dump(seed, f)
        boot = ("import sys; sys.path.insert(0, r'%s'); "
                "import deepseek_pet as dp; dp.CONFIG_PATH = r'%s'; "
                "sys.exit(dp.main())") % (SRCDIR, tmp_cfg)
        print(f"[i] 解释器: {PY}（临时配置，角色高度 {height}px）")

    before = set(find_windows(TITLE))
    if before:
        print(f"[i] 检测到已有 {len(before)} 个同名窗口（你自己的实例），本次只测新起的那个")

    # 验证的是画面，不该顺带联网，也不该读本机已安装的远端内容
    env = dict(os.environ)
    env["DPET_NO_UPDATE"] = "1"
    env["DPET_USER_CONTENT"] = os.path.join(tempfile.gettempdir(), "dpet_verify_nocontent")
    proc = subprocess.Popen([PY, "-c", boot], cwd=ROOT, env=env)
    try:
        hwnd = None
        for _ in range(40):
            time.sleep(0.25)
            new = set(find_windows(TITLE)) - before
            if new:
                hwnd = sorted(new)[0]
                break
        if not hwnd:
            print("[X] 没找到桌宠窗口——进程可能已退出。")
            print(f"    returncode = {proc.poll()}")
            return 1

        w, h, lx, ly = window_rect(hwnd)
        print(f"[OK] 找到窗口 hwnd={hwnd}  pid={pid_of(hwnd)}  位置=({lx},{ly})  尺寸={w}x{h}")
        if height:
            print(f"     期望角色高度 {height}px" +
                  ("（含动效边距，窗口会比角色略大）" if True else ""))

        time.sleep(1.5)                      # 等首帧稳定

        shots = []
        for i in range(6):
            img, size, alpha = grab(hwnd)
            shots.append(img)
            print(f"    抓取 {i+1}: {size}  非透明像素占比 {alpha*100:.1f}%")
            time.sleep(0.42)

        base = shots[0]
        print("=== 帧间差异（对比第 1 帧）===")
        alive = 0
        for i, s in enumerate(shots[1:], start=2):
            d = diff_ratio(base, s)
            if d > 0.004:
                alive += 1
            print(f"    第1帧 vs 第{i}帧: {d*100:.2f}%")

        # 落临时目录，不要落源码目录：这是每次跑都会覆盖的调试图，
        # 丢在 tools/ 下会让 git status 一直挂一个未跟踪文件。
        out = os.path.join(tempfile.gettempdir(), f"dpet_live_grab_{height or 'cur'}.png")
        shots[-1].save(out)
        print(f"[i] 末帧已存 {out}")

        if alive >= 4:
            print("[PASS] 真机上画面确实在动。")
            return 0
        print("[FAIL] 帧间几乎无变化，动画没生效。")
        return 2
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        print("[i] 桌宠进程已关闭。")
        if height is not None:
            try:
                os.remove(tmp_cfg)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
