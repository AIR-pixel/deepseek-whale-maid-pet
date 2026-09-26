# -*- coding: utf-8 -*-
"""交互音效播放。

三个必须处理好的点
------------------
1. **QSoundEffect 是异步加载的**：未 Ready 时调用 `play()` 直接无效（不报错）。
   点击反馈音绝不能"第一次点没声音"，所以启动时一次性预载并等它们就绪。
2. **不同 cue 几乎同时触发会叠成怪音**：比如点击既触发状态音又触发气泡音。
   用一个全局最小间隔挡掉后到的那个即可（同一 cue 连打由 QSoundEffect 自己合并，
   实测连打 3 次只响 1 次，不需要额外防抖）。
3. **任何失败都静默降级**：没声音可以接受，桌宠崩掉不行。
"""
import glob
import os
import time

from PyQt5.QtCore import QUrl

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX_DIR = os.path.join(APP_DIR, "assets", "sfx")

GATE_MS = 110            # 不同 cue 之间的最小间隔


class Sfx(object):
    def __init__(self, enabled=True, volume=0.6, gate_ms=GATE_MS):
        self.enabled = bool(enabled)
        self.volume = _clamp01(volume)
        self.gate = max(0, gate_ms) / 1000.0
        self.ok = False
        self.reason = ""
        self.ready = 0
        self.played = 0
        self.gated = 0
        self.missed = 0
        self._fx = {}
        self._last = -1e9
        self._load()

    # ------------------------------------------------------------ 加载
    def _load(self):
        try:
            from PyQt5.QtMultimedia import QSoundEffect
        except Exception as e:                       # 缺 QtMultimedia 也不影响桌宠
            self.reason = "QtMultimedia 不可用: %s" % (e,)
            return
        self._QSE = QSoundEffect
        for path in sorted(glob.glob(os.path.join(SFX_DIR, "*.wav"))):
            name = os.path.splitext(os.path.basename(path))[0]
            fx = QSoundEffect()
            fx.setSource(QUrl.fromLocalFile(path))
            fx.setVolume(self.volume)
            self._fx[name] = fx
        if not self._fx:
            self.reason = "assets/sfx 下没有 wav"
            return
        self.ok = True

    def wait_ready(self, timeout_ms=800):
        """等异步加载完成。返回就绪条数。

        只在启动时调用一次；构造窗口后、播放问候音之前。
        """
        if not self.ok:
            return 0
        from PyQt5.QtCore import QEventLoop, QTimer

        loading = lambda: any(f.status() == self._QSE.Loading for f in self._fx.values())
        if loading():
            loop = QEventLoop()
            for f in self._fx.values():
                f.statusChanged.connect(lambda *_: None if loading() else loop.quit())
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(timeout_ms)
            loop.exec_()
            timer.stop()
        self.ready = sum(1 for f in self._fx.values() if f.status() == self._QSE.Ready)
        bad = [n for n, f in self._fx.items() if f.status() == self._QSE.Error]
        if bad:
            self.reason = "加载失败: " + ", ".join(bad)
        return self.ready

    # ------------------------------------------------------------ 播放
    def play(self, name):
        """播放一个 cue。返回是否真的发出去了（便于测试断言）。"""
        if not self.ok or not self.enabled or self.volume <= 0.0:
            return False
        fx = self._fx.get(name)
        if fx is None or fx.status() != self._QSE.Ready:
            self.missed += 1
            return False
        now = time.monotonic()
        if now - self._last < self.gate:             # 挡掉几乎同时触发的第二条
            self.gated += 1
            return False
        self._last = now
        fx.play()
        self.played += 1
        return True

    def stop(self):
        for fx in self._fx.values():
            fx.stop()

    # ------------------------------------------------------------ 设置
    def set_volume(self, v):
        self.volume = _clamp01(v)
        for fx in self._fx.values():
            fx.setVolume(self.volume)
        return self.volume

    def set_enabled(self, on):
        self.enabled = bool(on)
        if not self.enabled:
            self.stop()
        return self.enabled

    def describe(self):
        if not self.ok:
            return "音效不可用（%s）" % (self.reason or "未知原因",)
        if not self.enabled:
            return "音效已关闭"
        return "音效 %d 条 · 音量 %d%%" % (self.ready or len(self._fx),
                                            round(self.volume * 100))


def _clamp01(v):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0
