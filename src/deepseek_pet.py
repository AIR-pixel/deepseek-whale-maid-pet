# -*- coding: utf-8 -*-
"""DeepSeek 鲸鱼娘 · 桌面宠物

轻量实现：仅依赖 PyQt5，素材为透明 WebP。
角色形象：社区二创「女仆鲸鱼娘」（OC「溟月」衍生，CC BY-NC-SA 4.0，非商用）。
"""
import ctypes
import json
import math
import os
import random
import sys
from ctypes import wintypes
from datetime import datetime

from PyQt5.QtCore import (QEasingCurve, QCoreApplication, QPoint,
                          QPropertyAnimation, QRectF, Qt, QTimer, pyqtProperty)
from PyQt5.QtGui import (QBitmap, QColor, QFont, QFontMetrics, QImage,
                         QPainter, QPainterPath, QPixmap, QRegion)
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QMenu,
                             QSystemTrayIcon, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lines  # noqa: E402
import motion  # noqa: E402
import sfx  # noqa: E402


def pin_qt_plugins():
    """把 PyQt5 自带的 Qt 插件目录，用 Python 的 Unicode 路径直接喂给 Qt。

    非做不可，原因很坑：路径里只要含一个非 ASCII 字符，Qt 推导 Qt5Core.dll
    所在目录时用的是窄字符 API，算出来的路径会变成一串 '?'，于是
    `QCoreApplication.libraryPaths()` 返回空 → 找不到平台插件 → Qt **弹一个
    模态错误框然后卡住**（不是崩溃，也没有 stderr，看起来就是"双击没反应"）。
    `qt.conf` 也救不了（它同样要经 Qt 的路径解析）。

    绕过办法：不让 Qt 自己推，从 PyQt5 包的实际位置手动加一条。
    Python 的 str→QString 走宽字符，中文路径不会失真；也不依赖系统 ANSI 代码页，
    比设 `QT_PLUGIN_PATH` 环境变量更稳（那个在非中文区域设置下会再翻一次车）。
    """
    try:
        import PyQt5
        cand = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
        if os.path.isdir(cand):
            QCoreApplication.addLibraryPath(cand)
    except Exception:
        pass          # 加不上也不能挡住启动，让 Qt 走它自己的默认逻辑


pin_qt_plugins()      # 必须在任何 QApplication 构造之前生效

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(APP_DIR, "assets", "pet")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

TICK_MS = 40            # 主循环 25fps

# 角色高度可调范围（逻辑像素）。80 已能看清表情，再小就只剩一个色块了。
MIN_H, MAX_H = 80, 560
# 滚轮每跳的像素数：小尺寸用细档，否则 80 高时一跳就是 25%，没法微调
WHEEL_FINE, WHEEL_COARSE, WHEEL_SWITCH = 10, 20, 240

DEFAULT_CFG = {
    "x": None, "y": None,
    "height": 280,
    "opacity": 1.0,
    "on_top": True,
    "bubble": True,
    "remind_water": False,
    "remind_sit": False,
    "mute_speech": False,
    "sfx": True,                # 交互音效总开关
    "sfx_volume": 0.6,          # 0.0 ~ 1.0
}

# 进入某状态时播什么音。只列"由用户动作或自发小动作触发"的状态——
# idle 是回退（响就吵）、doze/sleep 是人不在时才会进（响了没人听），都不给音。
STATE_CUE = {
    "happy":     "happy",
    "blindfold": "shy",
    "whale":     "whale",
    "eat":       "eat",
    "work":      "work",
}

# 自发小动作（用户没碰它，它自己换状态）要不要出声。
# 关掉是刻意的选择：需求是"交互反馈音"，每隔几十秒自己响一声会变成噪音。
# 想要"有生命感"就改成 True，一行的事。
AUTO_CUE = False

# ---------------------------------------------------------------- 系统空闲


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    """距离上一次键盘/鼠标输入的秒数"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
    except Exception:
        return 0.0


def screen_rect():
    app = QApplication.instance()
    return app.primaryScreen().availableGeometry()


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def self_usage():
    """返回 (累计 CPU 秒数, 内存 MB)，失败返回 (None, None)"""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        # 必须显式声明签名：伪句柄是 64 位，默认 c_int 会被截断
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.GetProcessTimes.argtypes = [
            wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wintypes.DWORD]

        h = k32.GetCurrentProcess()
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                   ctypes.byref(kernel), ctypes.byref(user)):
            return None, None
        cpu = (((kernel.dwHighDateTime << 32) | kernel.dwLowDateTime)
               + ((user.dwHighDateTime << 32) | user.dwLowDateTime)) / 1e7
        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        if not psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return cpu, None
        return cpu, pmc.WorkingSetSize / 1024 / 1024
    except Exception:
        return None, None


# ---------------------------------------------------------------- 气泡


class Bubble(QWidget):
    """角色头顶的台词气泡，不接收鼠标事件。"""

    MAX_W = 260

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._text = ""
        self._op = 0.0
        self._font = QFont("Microsoft YaHei UI", 9)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade)
        self._anim = QPropertyAnimation(self, b"opacity", self)
        self._anim.setDuration(240)
        self._anchor = QPoint(0, 0)

    # --- 动画属性
    @pyqtProperty(float)
    def opacity(self):
        return self._op

    @opacity.setter
    def opacity(self, v):
        self._op = v
        self.update()

    # --- 布局
    def _relayout(self):
        fm = QFontMetrics(self._font)
        pad_x, pad_y, tail = 13, 9, 7
        avail = self.MAX_W - pad_x * 2
        # 手动折行（按像素宽度）
        words, cur, out = list(self._text), "", []
        for ch in words:
            if fm.horizontalAdvance(cur + ch) <= avail:
                cur += ch
            else:
                out.append(cur)
                cur = ch
        if cur:
            out.append(cur)
        self._lines = out
        w = max(fm.horizontalAdvance(l) for l in out) + pad_x * 2
        w = max(w, 76)
        h = fm.height() * len(out) + pad_y * 2
        self.resize(int(w), int(h + tail))
        self._pad_x, self._pad_y, self._tail = pad_x, pad_y, tail

    def show_text(self, text, duration=3600):
        self._text = text
        self._relayout()
        self.reposition(self._anchor)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self._op)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
        self._hide_timer.start(duration)

    def reposition(self, anchor: QPoint):
        """anchor = 角色头顶中心点"""
        self._anchor = anchor
        x = anchor.x() - self.width() // 2
        y = anchor.y() - self.height() - 2
        sr = screen_rect()
        x = max(sr.left() + 2, min(x, sr.right() - self.width() - 2))
        y = max(sr.top() + 2, y)
        self.move(int(x), int(y))

    def _fade(self):
        self._anim.stop()
        self._anim.setStartValue(self._op)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InCubic)
        self._anim.start()
        QTimer.singleShot(260, self.hide)

    def paintEvent(self, _):
        if self._op <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._op)
        w, h = self.width(), self.height() - self._tail
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 11, 11)
        # 尾巴
        cx = w / 2
        path.moveTo(cx - 7, h - 1)
        path.lineTo(cx, h + self._tail - 1)
        path.lineTo(cx + 7, h - 1)
        path.closeSubpath()
        p.fillPath(path, QColor(30, 39, 62, 240))
        p.setPen(QColor(126, 178, 255, 170))
        p.drawPath(path)
        p.setPen(QColor(238, 244, 255))
        p.setFont(self._font)
        for i, line in enumerate(self._lines):
            p.drawText(self._pad_x, self._pad_y + (i + 1) * QFontMetrics(self._font).height() - 4,
                       line)


# ---------------------------------------------------------------- 桌宠窗口


class PetWindow(QWidget):
    # 状态 -> (素材名列表, 是否为临时状态, 持续毫秒范围)
    STATES = {
        "idle":      (["idle_open"], False, None),
        "work":      (["work_keypress", "work_desk"], False, None),
        "eat":       (["eat"], True, (2600, 3200)),
        "happy":     (["happy"], True, (2200, 2800)),
        "blindfold": (["blindfold"], True, (1800, 2400)),
        "whale":     (["whale"], True, (3200, 4200)),
        "doze":      (["doze"], False, None),
        "sleep":     (["sleep"], False, None),
    }

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if cfg.get("on_top", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("DeepSeek 鲸鱼娘")

        self._load_assets()

        # 动画 / 状态
        self._t = 0.0
        self._state = "idle"
        self._state_deadline = 0
        self._state_t0 = 0.0          # 进入当前状态的时刻，动效相位基准
        self._blink_until = 0
        self._next_blink = random.uniform(2.5, 6.0)
        self._op = float(cfg.get("opacity", 1.0))
        self._dragging = False
        self._moved = False
        self._press_global = QPoint()
        self._press_win = QPoint()
        self._press_time = 0
        self._fed = 0
        self._water_due = 45 * 60
        self._sit_due = 50 * 60
        self._speak_on_next_idle = False

        # 音效：必须在 _build_menu() 之前建好（菜单要读它的状态），
        # 也必须早于 _greet()（问候音要能立刻响）
        self.sfx = sfx.Sfx(enabled=cfg.get("sfx", True),
                           volume=cfg.get("sfx_volume", 0.6))

        self.bubble = Bubble()
        self._build_menu()

        self._apply_geometry(initial=True)
        self._render_frame("idle_open")
        self.sfx.wait_ready()             # 等异步加载，否则第一次点击会没声音
        self._greet()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(TICK_MS)

    # ------------------------------------------------ 素材
    def _load_assets(self):
        with open(os.path.join(ASSET_DIR, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        src = {m["name"]: m for m in manifest}
        self.pix = {}
        for name in src:
            pm = QPixmap(os.path.join(ASSET_DIR, name + ".webp"))
            if pm.isNull():
                raise RuntimeError("素材缺失: " + name)
            self.pix[name] = pm
        self._rescale()

    def _rescale(self):
        """按配置高度重算所有帧的显示尺寸（逻辑尺寸与物理像素分开记录）"""
        h = int(self.cfg.get("height", 280))
        self.scale_h = h
        dpr = self.dpr
        shown, lsize = {}, {}
        for name, pm in self.pix.items():
            fh = max(1, round(h * motion.VISUAL_SCALE.get(name, 1.0)))
            nw = max(1, round(pm.width() * fh / pm.height()))
            scaled = pm.scaled(int(nw * dpr), int(fh * dpr), Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            shown[name] = scaled
            lsize[name] = (nw, fh)
        self.shown = shown
        self.lsize = lsize
        # 动效：位移幅度随角色高度等比缩放，边距覆盖跳跃位移与旋转外溢
        self.motion_pad = motion.pad_for(max(hh for _, hh in lsize.values()))
        # 窗口尺寸 = 最大帧 + 动效余量（全部按逻辑像素）
        self.win_w = max(w for w, _ in lsize.values()) + self.motion_pad * 2
        self.win_h = max(hh for _, hh in lsize.values()) + self.motion_pad * 2

    # ------------------------------------------------ 几何
    def _apply_geometry(self, initial=False):
        self.resize(self.win_w, self.win_h)
        sr = screen_rect()
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if initial and (x is None or y is None):
            x = sr.right() - self.win_w - 60
            y = sr.bottom() - self.win_h - 24
        x = int(max(sr.left() - 40, min(int(x), sr.right() - 24)))
        y = int(max(sr.top(), min(int(y), sr.bottom() - 24)))
        self.move(x, y)

    def _frame_pos(self, name):
        w, h = self.lsize[name]
        x = (self.width() - w) // 2
        y = self.height() - h - self.motion_pad
        return x, y

    def _render_frame(self, name):
        self._cur = name
        pm = self.shown[name]
        x, y = self._frame_pos(name)
        # 用当前帧 alpha 生成窗口遮罩（精确命中 + 透明区鼠标穿透）。
        # 8 方向平移叠加 = 形态学膨胀，否则动效位移后的内容会被遮罩裁掉。
        canvas = QImage(self.width(), self.height(), QImage.Format_ARGB32)
        canvas.fill(0)
        p = QPainter(canvas)
        pad = self.motion_pad
        for i in range(8):
            ang = math.radians(i * 45)
            p.drawPixmap(int(x + pad * math.cos(ang)),
                         int(y + pad * math.sin(ang)), pm)
        p.end()
        self.setMask(QRegion(QBitmap.fromImage(canvas.createAlphaMask())))
        self.update()
        if self.bubble.isVisible():
            self._bubble_anchor()

    def _bubble_anchor(self):
        _, fh = self.lsize[self._cur]
        self.bubble.reposition(QPoint(self.x() + self.width() // 2,
                                      self.y() + self.height() - self.motion_pad - fh))

    # ------------------------------------------------ 状态机
    def _set_state(self, state, force=False, cue=True):
        """切换状态。

        cue=False 用于"这次交互已经播了更贴切的音"的场合——例如双击，
        画面进 happy 但该响的是蹦跳音 hop，不是通用开心音。
        """
        if state == self._state and not force:
            return
        if state not in self.STATES:
            return
        self._state = state
        self._state_t0 = self._t          # 动效相位归零，避免从半空中开始
        frames, temp, dur = self.STATES[state]
        self._render_frame(random.choice(frames))
        self._state_deadline = (self._t * 1000 + random.uniform(*dur)) if temp else 0
        if cue:
            name = STATE_CUE.get(state)
            if name:
                self.sfx.play(name)

    def _say(self, text, dur=3600, cue="pop"):
        """弹气泡。cue=None 表示这次不出声（调用方已经播过更贴切的音）。"""
        if cue:
            self.sfx.play(cue)
        if self.cfg.get("mute_speech") or not self.cfg.get("bubble", True):
            return
        self._bubble_anchor()
        self.bubble.show_text(text, dur)

    def _speak_state(self, cue="pop"):
        pool = lines.BY_STATE.get(self._state) or lines.POKE
        self._say(random.choice(pool), cue=cue)

    def _greet(self):
        self._say(random.choice(lines.greet_by_hour(datetime.now().hour)), 4200,
                  cue="hello")

    def _tick(self):
        self._t += TICK_MS / 1000.0
        ms = self._t * 1000

        # 临时状态到期 -> 回 idle
        if self._state_deadline and ms >= self._state_deadline:
            self._set_state("idle", force=True)

        idle = idle_seconds()

        # 空闲 -> 犯困 -> 睡觉
        if self._state in ("idle", "work"):
            if idle > 600:
                self._set_state("sleep")
            elif idle > 180:
                self._set_state("doze")
        elif self._state in ("doze", "sleep") and idle < 5:
            self._set_state("idle", force=True)
            self._say(random.choice(lines.WAKE), cue="wake")

        # 待机时自发小动作（用户没碰它 —— 默认不出声，见 AUTO_CUE 注释）
        if self._state == "idle" and random.random() < 0.0016:
            self._set_state(random.choice(["whale", "happy", "work"]), cue=AUTO_CUE)
        elif self._state == "work" and random.random() < 0.0012:
            self._set_state("idle", force=True, cue=False)

        # 定时提醒
        if self.cfg.get("remind_water") and self._t >= self._water_due:
            self._water_due = self._t + 45 * 60
            self._say(random.choice(lines.REMIND["water"]), cue="remind")
        if self.cfg.get("remind_sit") and self._t >= self._sit_due:
            self._sit_due = self._t + 50 * 60
            self._set_state("happy", force=True, cue=False)
            self._say(random.choice(lines.REMIND["sit"]), 5000, cue="remind")

        # 动效：所有状态都有运动曲线，每帧重绘
        self.update()

        # 眨眼
        if self._state == "idle":
            if ms < self._blink_until:
                if self._cur != "idle_blink":
                    self._render_frame("idle_blink")
            else:
                if self._cur == "idle_blink":
                    self._render_frame("idle_open")
                if self._t >= self._next_blink:
                    self._next_blink = self._t + random.uniform(2.4, 7.0)
                    self._blink_until = ms + 120
                    self._render_frame("idle_blink")

    # ------------------------------------------------ 绘制
    def paintEvent(self, _):
        name = self._cur
        pm = self.shown[name]
        x, y = self._frame_pos(name)
        lw, lh = self.lsize[name]
        dx, dy, sx, sy, rot = motion.params(name, self._t - self._state_t0,
                                            motion.scale_for(lh))

        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(self._op)

        # 以「脚底中心」为锚点做变换：呼吸时脚不动，蹦跳时整个人离地，
        # 压扁时从脚底往上缩——角色不会在窗口里乱飘。
        ax = x + lw / 2.0
        ay = y + float(lh)
        p.translate(ax + dx, ay + dy)
        if rot:
            p.rotate(rot)
        if sx != 1.0 or sy != 1.0:
            p.scale(sx, sy)
        p.translate(-ax, -ay)
        p.drawPixmap(int(x), int(y), pm)

    # ------------------------------------------------ 交互
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._moved = False
            self._press_global = e.globalPos()
            self._press_win = self.pos()
            self._press_time = self._t
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging and (e.buttons() & Qt.LeftButton):
            delta = e.globalPos() - self._press_global
            if delta.manhattanLength() > 4:
                if not self._moved:
                    self._moved = True
                    self.sfx.play("grab")
                    self._say(random.choice(lines.DRAG), 1800, cue=None)
                self.move(self._press_win + delta)
                if self.bubble.isVisible():
                    self._bubble_anchor()
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        was_drag = self._moved
        self._dragging = False
        self._moved = False
        if was_drag:
            self.sfx.play("drop")
        else:
            self._on_click(e)
        self._save_pos()

    def _on_click(self, e):
        if self._state == "sleep":
            self._set_state("idle", force=True)
            self._say(random.choice(lines.WAKE), cue="wake")
            return
        if self._state == "eat":
            self._fed += 1
        roll = random.random()
        if self._state == "doze":
            self._set_state("happy", force=True)
            self._say(random.choice(lines.WAKE), cue=None)
        elif roll < 0.42:
            self._set_state("happy", force=True)
            self._speak_state(cue=None)
        elif roll < 0.62:
            self._set_state("blindfold", force=True)
            self._say(random.choice(lines.SHY), cue=None)
        elif roll < 0.76:
            self._set_state("whale", force=True)
            self._say(random.choice(lines.WHALE), cue=None)
        elif roll < 0.86:
            self._set_state("eat", force=True)
            self._say(random.choice(lines.EAT), cue=None)
        else:
            self.sfx.play("click")
            self._speak_state(cue=None)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 双击专属音：先播 hop，画面再进 happy（happy 的通用音已由 cue=False 让位）
            self.sfx.play("hop")
            self._set_state("happy", force=True, cue=False)
            self._say(random.choice(lines.DBLCLICK), cue=None)
            self._moved = True  # 避免再触发单击

    def wheelEvent(self, e):
        cur = self.cfg.get("height", 280)
        unit = WHEEL_FINE if cur < WHEEL_SWITCH else WHEEL_COARSE
        up = e.angleDelta().y() > 0
        step = unit if up else -unit
        new_h = max(MIN_H, min(MAX_H, cur + step))
        if new_h != cur:
            old_bc = QPoint(self.x() + self.width() // 2, self.y() + self.height())
            self.cfg["height"] = new_h
            self._rescale()
            self.resize(self.win_w, self.win_h)
            self.move(old_bc.x() - self.win_w // 2, old_bc.y() - self.win_h)
            self._render_frame(self._cur)
            self._save()
            self.sfx.play("zoom_up" if up else "zoom_down")

    # ------------------------------------------------ 菜单
    def _build_menu(self):
        m = QMenu()
        m.setFont(QFont("Microsoft YaHei UI", 9))

        a = QAction("说句话", m)
        a.triggered.connect(self._speak_state)
        m.addAction(a)
        a = QAction("敲会儿键盘", m)
        a.triggered.connect(lambda: self._set_state("work", True))
        m.addAction(a)
        a = QAction("干饭", m)
        a.triggered.connect(lambda: (self._set_state("eat", True),
                                     self._say(random.choice(lines.EAT))))
        m.addAction(a)
        a = QAction("变回原型", m)
        a.triggered.connect(lambda: (self._set_state("whale", True),
                                     self._say(random.choice(lines.WHALE))))
        m.addAction(a)
        m.addSeparator()

        size = m.addMenu("大小")
        presets = [("迷你", 90), ("很小", 130), ("小", 190), ("标准", 280),
                   ("大", 380), ("很大", 460), ("超大", 560)]
        # 滚轮可连续缩放，高度未必正好等于预设值 —— 勾选最接近的那一档
        cur_h = self.cfg.get("height", 280)
        near = min(presets, key=lambda kv: abs(kv[1] - cur_h))[1]
        for label, h in presets:
            act = QAction(label, size)
            act.setCheckable(True)
            act.setChecked(near == h)
            act.triggered.connect(lambda _, hh=h: self._set_height(hh))
            size.addAction(act)

        op = m.addMenu("透明度")
        for label, v in [("100%", 1.0), ("90%", 0.9), ("75%", 0.75), ("60%", 0.6)]:
            act = QAction(label, op)
            act.setCheckable(True)
            act.setChecked(abs(self.cfg.get("opacity", 1.0) - v) < 0.01)
            act.triggered.connect(lambda _, vv=v: self._set_opacity(vv))
            op.addAction(act)

        m.addSeparator()
        top = QAction("始终置顶", m)
        top.setCheckable(True)
        top.setChecked(self.cfg.get("on_top", True))
        top.triggered.connect(self._toggle_top)
        m.addAction(top)

        bub = QAction("显示气泡", m)
        bub.setCheckable(True)
        bub.setChecked(self.cfg.get("bubble", True))
        bub.triggered.connect(self._toggle_bubble)
        m.addAction(bub)

        snd = QAction("交互音效", m)
        snd.setCheckable(True)
        snd.setChecked(bool(self.cfg.get("sfx", True)) and self.sfx.ok)
        snd.setEnabled(self.sfx.ok)          # 后端不可用时置灰而不是假装能开
        if not self.sfx.ok:
            snd.setToolTip(self.sfx.describe())
        snd.triggered.connect(self._toggle_sfx)
        m.addAction(snd)

        vol = m.addMenu("音效音量")
        vol.setEnabled(self.sfx.ok and bool(self.cfg.get("sfx", True)))
        cur_v = self.cfg.get("sfx_volume", 0.6)
        for label, v in [("20%", 0.2), ("40%", 0.4), ("60%", 0.6),
                         ("80%", 0.8), ("100%", 1.0)]:
            act = QAction(label, vol)
            act.setCheckable(True)
            act.setChecked(abs(cur_v - v) < 0.01)
            act.triggered.connect(lambda _, vv=v: self._set_sfx_volume(vv))
            vol.addAction(act)
        tip = QAction("试听", vol)
        tip.triggered.connect(lambda: self.sfx.play("happy"))
        vol.addSeparator()
        vol.addAction(tip)

        water = QAction("喝水提醒", m)
        water.setCheckable(True)
        water.setChecked(self.cfg.get("remind_water", False))
        water.triggered.connect(lambda v: self._toggle_remind("remind_water", v))
        m.addAction(water)

        sit = QAction("久坐提醒", m)
        sit.setCheckable(True)
        sit.setChecked(self.cfg.get("remind_sit", False))
        sit.triggered.connect(lambda v: self._toggle_remind("remind_sit", v))
        m.addAction(sit)

        self._autostart_action = QAction("开机自动启动", m)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(is_autostart())
        self._autostart_action.triggered.connect(self._toggle_autostart)
        m.addAction(self._autostart_action)

        m.addSeparator()
        a = QAction("资源占用", m)
        a.triggered.connect(self._report_usage)
        m.addAction(a)
        a = QAction("回到右下角", m)
        a.triggered.connect(self._reset_pos)
        m.addAction(a)
        a = QAction("关于", m)
        a.triggered.connect(self._about)
        m.addAction(a)
        m.addSeparator()
        a = QAction("退出", m)
        a.triggered.connect(QApplication.instance().quit)
        m.addAction(a)
        self.menu = m

    def _popup_menu(self, pos):
        # 每次弹出前重建：滚轮改过大小/换过透明度后，勾选要跟着实际状态走
        self._build_menu()
        self.menu.popup(pos)

    def contextMenuEvent(self, e):
        self._popup_menu(e.globalPos())

    def _set_height(self, h):
        old_bc = QPoint(self.x() + self.width() // 2, self.y() + self.height())
        self.cfg["height"] = h
        self._rescale()
        self.resize(self.win_w, self.win_h)
        self.move(old_bc.x() - self.win_w // 2, old_bc.y() - self.win_h)
        self._render_frame(self._cur)
        self._save()

    def _set_opacity(self, v):
        self.cfg["opacity"] = v
        self._op = v
        self.update()
        self._save()

    def _toggle_top(self, v):
        self.cfg["on_top"] = bool(v)
        flags = self.windowFlags()
        if v:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self._render_frame(self._cur)
        self._save()

    def _toggle_bubble(self, v):
        self.cfg["bubble"] = bool(v)
        if not v:
            self.bubble.hide()
        self._save()

    def _toggle_sfx(self, v):
        self.cfg["sfx"] = bool(v)
        self.sfx.set_enabled(v)
        self._save()
        if v:
            self.sfx.play("click")     # 立刻给个反馈，确认开对了

    def _set_sfx_volume(self, v):
        self.cfg["sfx_volume"] = self.sfx.set_volume(v)
        self._save()
        self.sfx.play("click")

    def _toggle_remind(self, key, v):
        self.cfg[key] = bool(v)
        if key == "remind_water":
            self._water_due = self._t + 45 * 60
        if key == "remind_sit":
            self._sit_due = self._t + 50 * 60
        self._save()

    def _toggle_autostart(self, v):
        ok = set_autostart(bool(v))
        if not ok:
            self._autostart_action.setChecked(is_autostart())
        else:
            self.cfg["autostart"] = bool(v)
            self._save()

    def _reset_pos(self):
        sr = screen_rect()
        self.move(sr.right() - self.win_w - 60, sr.bottom() - self.win_h - 24)
        self._save_pos()

    def _report_usage(self):
        cpu, mem = self_usage()
        if cpu is None:
            self._say("读不到占用数据。", 4000)
            return
        uptime = max(self._t, 1.0)
        self._say(f"运行 {uptime/60:.0f} 分钟 · CPU 均值 {cpu/uptime*100:.1f}% · 内存 {mem:.0f} MB", 6500)

    def _about(self):
        self._say("我是 DeepSeek 的鲸鱼娘。给饭就干活。", 5000)

    # ------------------------------------------------ 持久化
    def _save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _save_pos(self):
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        self._save()

    def closeEvent(self, e):
        self._save_pos()
        self.bubble.hide()
        e.accept()


# ---------------------------------------------------------------- 开机自启


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DeepSeekPet"


def _launch_cmd():
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{os.path.join(APP_DIR, "src", "deepseek_pet.py")}"'


def is_autostart() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:
        return False


def set_autostart(enable: bool) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _launch_cmd())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 托盘


def make_tray_icon(pet: PetWindow):
    pm = pet.pix["idle_open"]
    scaled = pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    from PyQt5.QtGui import QIcon
    icon = QIcon(scaled)
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("DeepSeek 鲸鱼娘 · 桌宠")
    menu = QMenu()
    menu.setFont(QFont("Microsoft YaHei UI", 9))
    a = QAction("显示 / 隐藏", menu)
    a.triggered.connect(lambda: pet.setVisible(not pet.isVisible()))
    menu.addAction(a)
    def tray_speak():
        pet.sfx.play("click")
        pet._speak_state(cue=None)

    a = QAction("说句话", menu)
    a.triggered.connect(tray_speak)
    menu.addAction(a)
    a = QAction("音效", menu)
    a.setCheckable(True)
    a.setChecked(bool(pet.cfg.get("sfx", True)) and pet.sfx.ok)
    a.setEnabled(pet.sfx.ok)
    a.triggered.connect(pet._toggle_sfx)
    menu.addAction(a)
    menu.addSeparator()
    a = QAction("设置（右键桌宠）", menu)
    a.triggered.connect(lambda: pet._popup_menu(pet.frameGeometry().topLeft()))
    menu.addAction(a)
    a = QAction("退出", menu)
    a.triggered.connect(QApplication.instance().quit)
    menu.addAction(a)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda r: pet.setVisible(not pet.isVisible())
        if r == QSystemTrayIcon.Trigger else None)
    tray.show()
    return tray


# ---------------------------------------------------------------- 入口


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    # 手改过或旧版本留下的尺寸要夹回合法区间，否则会撑出一个离谱的大窗口
    try:
        cfg["height"] = max(MIN_H, min(MAX_H, int(cfg.get("height", 280))))
    except (TypeError, ValueError):
        cfg["height"] = DEFAULT_CFG["height"]
    try:
        cfg["sfx_volume"] = max(0.0, min(1.0, float(cfg.get("sfx_volume", 0.6))))
    except (TypeError, ValueError):
        cfg["sfx_volume"] = DEFAULT_CFG["sfx_volume"]
    return cfg


def main():
    pin_qt_plugins()      # 幂等，再确认一次：必须在 QApplication 之前
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    cfg = load_cfg()
    pet = PetWindow(cfg)
    pet.show()
    tray = make_tray_icon(pet)
    app._tray = tray  # 保持引用
    app._pet = pet
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
