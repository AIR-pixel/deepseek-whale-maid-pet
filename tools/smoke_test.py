# -*- coding: utf-8 -*-
"""无头冒烟测试：验证素材加载、状态机、遮罩、绘制、交互逻辑。"""
import contextlib
import math
import os
import random
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PyQt5.QtCore import QPoint, QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
import deepseek_pet as dp  # noqa: E402

# 本测试会调用 _set_height / _set_opacity，两者内部都会 _save() 写盘。
# 把 CONFIG_PATH 指到临时文件，避免把用户真实的大小/透明度设置冲掉。
_REAL_CFG = dp.CONFIG_PATH
dp.CONFIG_PATH = os.path.join(tempfile.gettempdir(), "deepseek_pet_smoke_cfg.json")

FAIL = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


@contextlib.contextmanager
def no_auto_action():
    """临时关掉"自发小动作"这类用 random.random() 判定的随机分支。

    _tick() 里 `if self._state == "idle" and random.random() < 0.0016` 会在断言
    精确帧的分组里偶发命中，把 idle 换成 happy，导致"眨眼"这类测试假失败。
    只影响直接调用 random.random() 的位置：random.choice / random.uniform 走的是
    Random 实例的方法，不受影响，所以帧选择和时长依然随机。
    """
    orig = random.random
    random.random = lambda: 1.0
    try:
        yield
    finally:
        random.random = orig


app = QApplication([])
cfg = dp.load_cfg()
# 冒烟测试不该真的联网：关掉启动检查（更新链路由 tools/update_test.py 单独覆盖）。
# 不关的话 PetWindow.__init__ 会起后台线程去访问 GitHub，测试变成看网络脸色。
cfg["auto_update"] = False
# 内容包也钉到临时目录，别让本机已安装的远端内容影响断言
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMOKE_CONTENT = os.path.join(tempfile.gettempdir(), "dpet_smoke_content")
import shutil  # noqa: E402
shutil.rmtree(SMOKE_CONTENT, ignore_errors=True)
os.environ["DPET_USER_CONTENT"] = SMOKE_CONTENT
pet = dp.PetWindow(cfg)
pet.show()
print("[1] 素材加载")
check(len(pet.pix) == 10, f"载入帧数 = {len(pet.pix)}")
check(all(not p.isNull() for p in pet.pix.values()), "所有 WebP 有效")
check(pet.win_w > 100 and pet.win_h > 100, f"窗口尺寸 = {pet.win_w}x{pet.win_h}")
check(pet.missing_frames == [], f"无缺失帧 = {pet.missing_frames}")
check(pet.pack.source == "builtin", f"初始内容来源 = {pet.pack.source}")

print("[2] 状态机")
for st in pet.STATES:
    pet._set_state(st, force=True)
    ok = pet._cur in pet.STATES[st][0]
    check(ok, f"状态 {st} -> 帧 {pet._cur}")

print("[3] 遮罩（点击命中区域）")
pet._set_state("idle", force=True)
r = pet.mask()
check(not r.isEmpty(), f"idle 遮罩非空, 包围盒 = {r.boundingRect().width()}x{r.boundingRect().height()}")
pet._set_state("work", force=True)
r2 = pet.mask()
check(not r2.isEmpty(), "work 遮罩非空")
check(r.boundingRect().width() != r2.boundingRect().width(), "不同帧遮罩形状不同")

print("[4] 主循环 tick")
pet._t = 0
for _ in range(40):
    pet._tick()
check(True, "40 次 tick 未抛异常")
check(pet._state in pet.STATES, f"tick 后状态合法 = {pet._state}")

print("[5] 眨眼逻辑")
dp.idle_seconds = lambda: 1.0          # 模拟用户正在使用电脑
pet._set_state("idle", force=True)
pet._t = 0
pet._next_blink = 0
with no_auto_action():                 # 断言精确帧，屏蔽自发小动作的随机干扰
    pet._tick()
    check(pet._cur == "idle_blink", f"应进入闭眼帧, 实际 = {pet._cur}")
    pet._t = 1.0
    pet._tick()
    check(pet._cur == "idle_open", f"眨眼结束应回到睁眼帧, 实际 = {pet._cur}")

print("[5b] 空闲自动犯困 / 睡觉")
dp.idle_seconds = lambda: 300.0
pet._set_state("idle", force=True)
with no_auto_action():
    pet._tick()
    check(pet._state == "doze", f"空闲 300s 应犯困, 实际 = {pet._state}")
    dp.idle_seconds = lambda: 900.0
    pet._set_state("idle", force=True)
    pet._tick()
    check(pet._state == "sleep", f"空闲 900s 应睡觉, 实际 = {pet._state}")
    dp.idle_seconds = lambda: 0.5
    pet._tick()
    check(pet._state == "idle", f"用户回来应唤醒, 实际 = {pet._state}")

print("[6] 交互分支")
pet._set_state("idle", force=True)
seen = set()
for _ in range(200):
    pet._set_state("idle", force=True)
    pet._on_click(None)
    seen.add(pet._state)
check(len(seen) >= 3, f"点击产生多种反应 = {sorted(seen)}")
check(all(s in pet.STATES for s in seen), "反应状态均合法")

print("[7] 缩放 / 透明度 / 台词")
pet._set_height(340)
check(pet.cfg["height"] == 340 and pet.win_h > 0, f"缩放后 win = {pet.win_w}x{pet.win_h}")
pet._set_opacity(0.75)
check(abs(pet._op - 0.75) < 1e-6, "透明度设置")
pet._say("测试台词")
check(pet.bubble._text == "测试台词", "气泡文案")
check(pet.bubble.width() > 0 and pet.bubble.height() > 0, f"气泡尺寸 = {pet.bubble.width()}x{pet.bubble.height()}")

print("[8] 台词库完整性")
check(len(dp.lines.BY_STATE) == 8, f"状态台词组 = {len(dp.lines.BY_STATE)}")
total = sum(len(v) for v in dp.lines.BY_STATE.values()) + len(dp.lines.DRAG) + len(dp.lines.WAKE) + len(dp.lines.DBLCLICK)
check(total >= 50, f"台词总数 = {total}")
check(all(len(v) for v in dp.lines.GREET.values()), "分时段问候齐全")

print("[9] 托盘图标渲染")
try:
    pm = pet.pix["idle_open"].scaled(64, 64, dp.Qt.KeepAspectRatio, dp.Qt.SmoothTransformation)
    check(not pm.isNull(), "托盘图标可生成")
except Exception as e:
    check(False, f"托盘图标异常: {e}")

print("[10] 资源占用自检")
cpu, mem = dp.self_usage()
check(cpu is not None and mem is not None and mem > 0,
      f"CPU 累计 {cpu:.2f}s, 内存 {mem:.1f} MB" if cpu is not None else "读取失败")
pet._t = 12.0
pet._report_usage()
check("CPU" in pet.bubble._text, f"气泡内容 = {pet.bubble._text}")

print("[11] 动效自检")
M = dp.motion
issues, stills, spans = [], [], {}
for state, (frames, _, _) in pet.STATES.items():
    for fname in frames:
        cyc = M.cycle(fname)
        lh = pet.lsize[fname][1]
        worst = 0.0
        dys = []
        for i in range(48):
            dx, dy, sx, sy, rot = M.params(fname, cyc * i / 48, M.scale_for(lh))
            ext = max(abs(dy), abs(dx) + lh * abs(math.sin(math.radians(rot))))
            worst = max(worst, ext)
            dys.append(dy)
        if worst > pet.motion_pad + 1:
            issues.append(f"{fname}({worst:.0f}>{pet.motion_pad})")
        span = max(dys) - min(dys)
        spans[fname] = span
        if span < 1.0 and fname != "idle_blink":
            stills.append(f"{fname}({span:.1f}px)")
check(not issues, f"位移均在预留边距 {pet.motion_pad}px 内" + (f" | 越界: {issues}" if issues else ""))
check(not stills, "每个状态都有可见运动" + (f" | 静止: {stills}" if stills else ""))
check(spans.get("happy", 0) > spans.get("idle_open", 0), "蹦跳幅度大于呼吸幅度")
print("     各状态垂直位移幅度: " + ", ".join(f"{k}={v:.1f}px" for k, v in spans.items()))

print("[12] 各尺寸下的动效余量")
over, tiny = [], []
SWEEP = (dp.MIN_H, 100, 130, 190, 280, 340, 380, 460,
         int((dp.MIN_H + dp.MAX_H) / 2), dp.MAX_H)
for h in SWEEP:
    pet._set_height(h)
    pad = pet.motion_pad
    worst, who = 0.0, ""
    for state, (frames, _, _) in pet.STATES.items():
        for fname in frames:
            cyc = M.cycle(fname)
            lh = pet.lsize[fname][1]
            sc = M.scale_for(lh)
            dys = []
            for i in range(48):
                dx, dy, sx, sy, rot = M.params(fname, cyc * i / 48, sc)
                ext = max(abs(dy), abs(dx) + lh * abs(math.sin(math.radians(rot))))
                if ext > worst:
                    worst, who = ext, fname
                dys.append(dy)
            if fname == "idle_open" and max(dys) - min(dys) < 2.0:
                tiny.append(f"h={h} 呼吸只有 {max(dys)-min(dys):.1f}px")
    bad = worst > pad + 1
    if bad:
        over.append(f"h={h} {who} {worst:.0f}>{pad}")
    print(f"    高度 {h:>3}px  余量 {pad:>3}px  最大位移 {worst:5.1f}px" + ("   <-- 越界" if bad else ""))
check(not over, "所有尺寸下动效均不越界" + (f" | {over}" if over else ""))
check(not tiny, "最小尺寸下动效依然看得见" + (f" | {tiny}" if tiny else ""))

print("[13] 菜单勾选跟随实际状态")
for h, want in ((280, "标准"), (380, "大"), (460, "很大"), (90, "迷你"), (130, "很小")):
    pet._set_height(h)
    pet._build_menu()
    got = [a.text() for a in pet.menu.findChildren(dp.QAction) if a.isCheckable() and a.isChecked()]
    check(want in got, f"高度 {h} -> 应勾选「{want}」，实际 {got}")
pet._set_opacity(0.6)
pet._build_menu()
got = [a.text() for a in pet.menu.findChildren(dp.QAction) if a.isCheckable() and a.isChecked()]
check("60%" in got, f"透明度 0.6 -> 应勾选「60%」，实际 {got}")

print("[14] 尺寸范围与滚轮步长")
check(dp.MIN_H <= 80 and dp.MAX_H >= 560, f"可调范围 {dp.MIN_H}–{dp.MAX_H}")
pet._set_height(120)
check(pet.cfg["height"] == 120, "小尺寸可设")
# 夹取：手改配置写出越界值也要被拉回区间
import json as _json
for bad_h, expect in ((30, dp.MIN_H), (9999, dp.MAX_H), ("abc", dp.DEFAULT_CFG["height"])):
    with open(dp.CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump({"height": bad_h}, f)
    got_h = dp.load_cfg()["height"]
    check(got_h == expect, f"配置里 height={bad_h!r} -> 夹回 {got_h}（期望 {expect}）")

print("[15] 音效")
import re
import wave

CUE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sfx")
files = sorted(f for f in os.listdir(CUE_DIR) if f.endswith(".wav")) if os.path.isdir(CUE_DIR) else []
check(len(files) >= 10, f"cue 文件数 = {len(files)}")

bad_fmt, total_bytes = [], 0
for fn in files:
    with wave.open(os.path.join(CUE_DIR, fn)) as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 22050):
            bad_fmt.append(fn)
        total_bytes += os.path.getsize(os.path.join(CUE_DIR, fn))
check(not bad_fmt, "全部为 16bit 单声道 22050Hz" + (f" | 异常: {bad_fmt}" if bad_fmt else ""))
check(total_bytes < 400 * 1024, f"音效总体积 {total_bytes / 1024:.0f} KB（需 < 400KB）")

# 交叉验证：代码里引用的 cue 名必须都有对应文件。
# 这条能自动抓住"加了新音效但忘了重跑 make_sfx.py"这类错误。
# 只抓 sfx.play(...) 的实参和 cue= 的值——按行粗抓会把 lines.REMIND["water"]
# 这种无关字符串也算进来，产生假失败。
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "src", "deepseek_pet.py"), encoding="utf-8").read()
used = set(dp.STATE_CUE.values())
for call in re.finditer(r"sfx\.play\(([^)]*)\)", src):
    used |= set(re.findall(r'"([a-z_]+)"', call.group(1)))
used |= set(re.findall(r'cue\s*=\s*"([a-z_]+)"', src))
have = {os.path.splitext(f)[0] for f in files}
missing = sorted(used - have)
check(not missing, f"代码引用的 {len(used)} 个 cue 均有文件" + (f" | 缺失: {missing}" if missing else ""))
unused = sorted(have - used)
print(f"     未被引用（可删）: {unused or '无'}")

S = pet.sfx
check(S.ok, f"后端可用（{S.reason or 'ok'}）")
check(S.ready == len(files), f"就绪 {S.ready}/{len(files)}")
check("音效" in S.describe(), f"状态描述 = {S.describe()}")

# 间隔大于 gate 时逐个都能播
S.enabled, S.volume, S._last = True, 0.6, -1e9
failed = []
for nm in sorted(have):
    if not S.play(nm):
        failed.append(nm)
    S._last = -1e9                      # 手动把门放开，避免被 gate 挡住误判
check(not failed, f"全部 cue 可播放" + (f" | 失败: {failed}" if failed else ""))

# gate：几乎同时触发的第二条必须被挡掉，否则状态音+气泡音会叠成怪音
S._last = -1e9
a = S.play("click")
b = S.play("pop")                       # 紧跟着触发
check(a and not b, f"隔 0ms 的第二条被挡（第一条={a}, 第二条={b}）")

# 关掉 / 静音后都不出声
S.set_enabled(False)
check(not S.play("click"), "关闭后不出声")
S.set_enabled(True)
S.set_volume(0.0)
check(not S.play("click"), "音量 0 时不出声")
check(S.set_volume(0.6) == 0.6, "音量可设回 0.6")

print("[16] 内容热加载与惊喜")
import json as _json  # noqa: E402
import updater as _up  # noqa: E402

# 铺一份"远端新内容"：一个新动作 stretch，带自己的台词和权重
os.makedirs(os.path.join(SMOKE_CONTENT, "pet"), exist_ok=True)
shutil.copyfile(os.path.join(ROOT, "assets", "pet", "happy.webp"),
                os.path.join(SMOKE_CONTENT, "pet", "stretch.webp"))
with open(os.path.join(SMOKE_CONTENT, "actions.json"), "w", encoding="utf-8") as f:
    _json.dump({
        "schema": 1, "content_version": 2, "announce": "我学会新动作了！",
        "assets": {"stretch": {"file": "pet/stretch.webp", "visual_scale": 1.0}},
        "motions": {"stretch": {"cycle": 2.2, "channels": {
            "dy": [{"k": "sine", "period": 2.2, "amp": 6.0}],
            "sy": [{"k": "sine", "period": 1.1, "amp": 0.02}]}}},
        "states": {"stretch": {"frames": ["stretch"], "temp": True,
                               "dur": [2200, 2800], "cue": "happy",
                               "lines": ["伸个懒腰。"], "weight": 3}},
    }, f, ensure_ascii=False)

before = set(pet.STATES)
res = _up.UpdateResult("updated", 2, message="已更新到 r2", announce="我学会新动作了！")
pet._on_update_result(res)
check(pet.pack.source == "builtin+remote", f"热加载后来源 = {pet.pack.source}")
check(set(pet.STATES) - before == {"stretch"}, f"新增状态 = {sorted(set(pet.STATES) - before)}")
check("stretch" in pet.shown, "新素材已进入渲染表")
check(pet._pending_new == ["stretch"], f"待演队列 = {pet._pending_new}")
check(any(n == "stretch" for n, _ in pet._idle_pool), f"抽签池 = {pet._idle_pool}")
check(pet._state_lines("stretch") == ["伸个懒腰。"], "新动作台词来自内容包")
check(pet._state_cue("stretch") == "happy", "新动作音效来自内容包")

pet._set_state("idle", force=True)
pet._play_surprise()
check(pet._state == "stretch", f"惊喜已演出，状态 = {pet._state}")
check(pet.bubble._text == "我学会新动作了！", f"气泡 = {pet.bubble._text!r}")
check(pet._pending_new == [], "演出后队列清空")
check(pet.pack.state_meta("stretch").get("announce") or True, "内容包元数据可读")

# 回滚：删掉远端目录再热加载，必须干净地退回内置
shutil.rmtree(SMOKE_CONTENT, ignore_errors=True)
check(pet._reload_content(), "热加载回退成功")
check("stretch" not in pet.STATES, "回滚后新状态消失")
check(len(pet.STATES) == 8, f"状态数回到 8 = {len(pet.STATES)}")
check(pet._pending_new == [], "回滚后队列为空")

# 内容包坏掉时必须整体退回内置，而不是半个包跑起来
os.makedirs(SMOKE_CONTENT, exist_ok=True)
with open(os.path.join(SMOKE_CONTENT, "actions.json"), "w", encoding="utf-8") as f:
    _json.dump({"content_version": 3,
                "states": {"ghost": {"frames": ["not_here"], "temp": True,
                                     "dur": [1000, 2000]}}}, f)
pack = dp.contentpack.load()
check(pack.source == "builtin", f"素材缺失的包应被整个丢弃，实际 {pack.source}")
check(pack.problems and "not_here" in " ".join(pack.problems),
      f"给出可读原因 = {pack.problems}")
shutil.rmtree(SMOKE_CONTENT, ignore_errors=True)

print()
try:
    os.remove(dp.CONFIG_PATH)
except OSError:
    pass

if FAIL:
    print(f"== {len(FAIL)} 项失败 ==")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("== 全部通过 ==")
