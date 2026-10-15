#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机交互回归：面板改位置 + 悬浮窗触摸链路。

为什么需要这个脚本
------------------
手机版的坑几乎全在"事件到底有没有到"这一层，光读代码得不出结论。三种病的**表现一模一样**
（"点它没反应"），但病因完全不同：

  1. 窗口被设成了 `FLAG_NOT_TOUCHABLE`（控制面板在前台时就是这样，这是设计，不是 bug）；
  2. 触摸落进了系统手势热区（左右边缘约 20dp 会被系统抢走，表现为"拖不动"）；
  3. 手势进行到一半，窗口因为换帧改了尺寸，这一串事件被判成 CANCEL。

区分它们的唯一办法是看设备的实况。logcat 在这台测试机（Redmi Note 11 / HyperOS）上
**完全不可用**（`logd not running`），所以判断依据是服务自己落盘的 `dpet.log` ——
"按下 / 抬手 / 单击 / 拖动"这几行直接回答"事件到没到"。

脚本把四件事串成一个可重复的流程：

  A. 面板里点预设「右上」→ 日志必须有 `位置: 锚点=...`，且锚点确实跑到屏幕上方；
  B. **反向验证**：面板还开着时，宠物窗的布局 flags 必须带 `FLAG_NOT_TOUCHABLE`；
     回到桌面后这面旗子必须摘掉 —— 用 dumpsys 读 flags，**不去合成点击**：
     那一下会穿透到面板控件上（可能正好落在"停止桌宠"或某根滑块上）。
  C. 回桌面后点宠物 → `触摸: 按下` + `触摸: 抬手` + `单击`；
  D. 回桌面后横向拖宠物 → `拖动: 开始` + `拖动: 结束`，且锚点水平位移与手势方向一致。

用法：
    python device_check.py                 # 装 + 跑全套
    python device_check.py --no-install    # 不重装，只跑流程
    python device_check.py --log           # 只把日志尾部打出来（排查用）
"""

import argparse
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dpetbuild as B  # noqa: E402

PKG = "dpet.app"
ACT = "dpet.app/.MainActivity"
BUILD = os.path.join(os.path.dirname(HERE), "app", "build")
APK = os.path.join(BUILD, "pet.apk")
LOG = "/sdcard/Android/data/%s/files/dpet.log" % PKG

_passed = []
_failed = []


def sh(args):
    return B.adb(["shell"] + args, check=False).stdout or ""


def read_log():
    return sh(["cat", LOG])


def tail_since(mark):
    """日志里从 mark（上一次读到的行数）之后的新行。"""
    all_lines = read_log().splitlines()
    return all_lines[mark:], len(all_lines)


def check(name, ok, detail=""):
    (_passed if ok else _failed).append(name)
    print("  [%s] %s%s" % ("OK" if ok else "!!", name, ("  — " + detail) if detail else ""))


def ui_dump():
    remote = "/sdcard/dpet-ui.xml"
    B.adb(["shell", "uiautomator", "dump", remote], check=False)
    local = os.path.join(BUILD, "ui-check.xml")
    if os.path.exists(local):
        os.remove(local)
    B.adb(["pull", remote, local], check=False)
    if not os.path.exists(local):
        return ""
    with open(local, encoding="utf-8", errors="replace") as f:
        return f.read()


def bounds_of(xml, text):
    m = re.search(
        r'text="%s"[^>]*?bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"' % re.escape(text), xml)
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def tap(xy, times=1, gap_ms=0):
    """点一下。

    [times=2] 只对**幂等**的按钮用（预设按钮点几次都是同一个值）：这台机器上
    `input tap` **偶发不生效**，连点两次明显更可靠。

    **开关绝不能这么干** —— 两次点击 = 开完又关，等于没动（而且日志里能抓到中间那次
    true，看着像生效了，实际停在 false）。开关要用 [toggle_until]，点一次就查一次状态。
    """
    x, y = xy
    for i in range(times):
        sh(["input", "tap", str(x), str(y)])
        if gap_ms and i + 1 < times:
            time.sleep(gap_ms / 1000.0)


def toggle_until(xy, needle, tries=3, timeout_s=2.5):
    """点开关，直到日志出现 [needle]。每次只点一下 —— 见 tap() 的说明。"""
    hit = False
    for attempt in range(tries):
        mark = len(read_log().splitlines())
        tap(xy)
        new, _ = wait_for(mark, needle, timeout_s)
        if needle in "\n".join(new):
            hit = True
            break
        B.log("第 %d 次点开关没生效（input tap 偶发丢），重试" % (attempt + 1))
    return hit


def tap_text(text, xml=None):
    xml = xml if xml is not None else ui_dump()
    b = bounds_of(xml, text)
    if not b:
        return False
    x1, y1, x2, y2 = b
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    B.log("点「%s」@ (%d,%d)" % (text, cx, cy))
    tap((cx, cy), times=2, gap_ms=260)     # 连点两次：`input tap` 在这台机器上偶发不生效
    return True


def parse_pos(lines):
    """从日志里取最近一条 `位置: 锚点=(x,y) 窗口=(wx,wy) WxH`。"""
    for line in reversed(lines):
        m = re.search(r"位置: 锚点=\((-?\d+),(-?\d+)\) 窗口=\((-?\d+),(-?\d+)\) (\d+)x(\d+)", line)
        if m:
            ax, ay, wx, wy, w, h = (int(g) for g in m.groups())
            # 宠物在窗口里恒为 (pad, pad) 处，锚点又是水平中心 ——
            # 所以"身上能被点到的位置"就是窗口的水平中点、纵向中段。
            return ax, ay, wx, wy, w, h
    return None


def wait_for(mark, needle, timeout_s=3.0, step=0.4):
    """轮询日志直到出现 [needle]，或超时。返回（这段时间的新行, 新的 mark）。

    为什么不用固定 sleep：这台机器上 `input tap` 偶发不生效，靠"等固定时长再看"
    会把"这次没点上"和"功能坏了"混成一谈。轮询到就立刻往下走，既快又准。
    """
    waited = 0.0
    while waited < timeout_s:
        new, mk = tail_since(mark)
        if needle in "\n".join(new):
            return new, mk
        time.sleep(step)
        waited += step
    return tail_since(mark)


def scroll_to_text(text, tries=3):
    """把面板滚到 [text] 可见。

    面板是 ScrollView，`uiautomator dump` **只给可见节点** —— 屏幕外的控件压根不在
    树里（"锁定位置"在页面下半部分，一开面板是 dump 不到的）。`KEYCODE_PAGE_DOWN`
    在这台机器上无效，只能靠滑动。

    起手点选在页面下缘（x=500, y=2270）：那里是开关行的说明文字，**不是滑块也不是
    开关**。ScrollView 一旦判定为滚动就会拦截后续 MOVE，所以滑过去时那四根 SeekBar
    不会跳值 —— 否则测一次就把"大小/透明度"改掉了。
    """
    for i in range(tries):
        xml = ui_dump()
        if bounds_of(xml, text):
            return xml
        sh(["input", "swipe", "500", "2270", "500", "1200", "300"])
        time.sleep(0.9)
    return ui_dump()


def switch_xy(xml, title):
    """某个开关行右侧那个 `Switch` 的中心坐标。

    界面是纯代码搭的，没有 resource-id，只能按"纵向位置和标题对齐的那个 Switch"来认。
    """
    tb = bounds_of(xml, title)
    if not tb:
        return None
    ty = (tb[1] + tb[3]) // 2
    best = None
    pat = r'class="android\.widget\.Switch"[^>]*?bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"'
    for m in re.finditer(pat, xml):
        x1, y1, x2, y2 = (int(g) for g in m.groups())
        cy = (y1 + y2) // 2
        d = abs(cy - ty)
        if best is None or d < best[0]:
            best = (d, (x1 + x2) // 2, cy)
    return (best[1], best[2]) if best else None


def last_flag_line(lines):
    """最近一条 `窗口 flags=0x... 可触摸/不吃触摸`。"""
    for line in reversed(lines):
        if "窗口 flags=" in line:
            return line
    return ""


def overlay_flags():
    """【已弃用】本想从 `dumpsys window windows` 里读窗口布局 flags，但测试机
    （HyperOS）的 dumpsys 输出里**列不出**我们这两个 overlay 窗 —— 只有
    `dumpsys window` 的 WindowState 块才带包名，而这家 ROM 不打印。

    改成读应用自己的日志（见 [last_flag_line]）：ROM 无关，而且它记的正是
    `applyFlags()` 真正写进去的那份 flags，比 dumpsys 更接近真相。
    """
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--log", action="store_true", help="只打印日志尾部")
    args = ap.parse_args()

    if B.device_serial() is None:
        print("没有检测到设备（adb devices 为空）。插上手机、开 USB 调试再跑。")
        sys.exit(1)

    if args.log:
        for line in read_log().splitlines()[-80:]:
            print(line)
        return

    B.step("安装")
    if not args.no_install:
        if not B.install_with_ui_fallback(APK, PKG, BUILD):
            sys.exit(1)
        B.adb(["shell", "appops", "set", PKG, "SYSTEM_ALERT_WINDOW", "allow"])
        B.adb(["shell", "pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS"])

    B.step("彻底重启（日志截断，后面只看这一轮）")
    # `sh -c "rm -f ..."` 在这里会被 adb 拆成 `sh -c rm`（只有 rm 被当成命令），
    # 删不掉任何东西 —— 直接 `rm -f <path>` 才对。删不掉也没关系（判定靠行号偏移），
    # 但留着旧日志会让人误判，所以还是删干净。
    sh(["am", "force-stop", PKG])
    time.sleep(1)
    sh(["rm", "-f", LOG])
    sh(["wm", "dismiss-keyguard"])

    B.step("打开控制面板")
    sh(["am", "start", "-n", ACT])
    time.sleep(3)
    xml = ui_dump()
    if not xml.strip():
        print("  uiautomator dump 拿不到界面 —— 手机可能还在锁屏，先手动解锁。")
        sys.exit(1)
    if bounds_of(xml, "开启桌宠"):
        B.log("桌宠没在跑，先开启")
        tap_text("开启桌宠", xml)
        time.sleep(3)
        xml = ui_dump()

    # ---------------------------------------------------------------- A
    #
    # 挑「中下」而不是四个角：宠物的可点位置会落在桌面中部偏下的空白处，
    # 万一触摸没到宠物，那一下也只会落到壁纸上，不会误开桌面的图标。
    B.step("A. 面板里改位置（点预设「中下」）")
    pos = None
    for attempt in range(3):
        mark = len(read_log().splitlines())
        if not tap_text("中下", xml if attempt == 0 else ui_dump()):
            check("面板里有「中下」预设", False, "uiautomator 里没找到这个按钮")
            sys.exit(1)
        new, mark = wait_for(mark, "位置:", 3.0)
        pos = parse_pos(new)
        if pos:
            break
        B.log("第 %d 次点预设没生效（input tap 偶发丢），重试" % (attempt + 1))
    check("点预设后服务应用了新位置", pos is not None,
          "" if pos else "日志里没有『位置:』这行，说明配置广播没到服务")
    if pos:
        ax, ay, wx, wy, w, h = pos
        m = re.search(r"(\d+)x(\d+)", sh(["wm", "size"]))
        sw, shh = (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)
        # 面板写 0.50w / 0.90h，服务端应该原样落在同一个点上（屏幕尺寸两边都走
        # DisplayManager.getRealMetrics，不该有系统性偏差；留 2% 容差给取整和钳制）
        ok = abs(ax - 0.50 * sw) <= sw * 0.02 and abs(ay - 0.90 * shh) <= shh * 0.02
        check("落点与面板里设的比例一致", ok,
              "锚点=(%d,%d) · 期望≈(%d,%d)" % (ax, ay, 0.50 * sw, 0.90 * shh))
        pet_xy = (ax, wy + h // 2)
        B.log("宠物可点位置 ≈ (%d,%d)" % pet_xy)
    else:
        pet_xy = (540, 1926)

    # ---------------------------------------------------------------- B
    #
    # 判定依据是**应用自己记的那行 flags**，不是合成点击：那一下点击会穿透到面板控件上
    # （宠物位置是浮动的，可能正好压在"停止桌宠"或某根开关上），测一次改坏一次环境。
    B.step("B. 面板开着 → 宠物窗不吃触摸；回桌面 → 这面旗子必须摘掉")
    line = last_flag_line(read_log().splitlines())
    check("读到宠物窗的 flags", bool(line), line)
    check("面板前台时宠物窗不吃触摸", "不吃触摸" in line if line else False, line)

    sh(["input", "keyevent", "KEYCODE_HOME"])
    time.sleep(1.5)
    line2 = last_flag_line(read_log().splitlines())
    check("回到桌面后触摸恢复", "可触摸" in line2, line2)

    # ---------------------------------------------------------------- C
    B.step("C. 回桌面后点宠物 —— 应该有完整的一次点击")
    joined = ""
    for attempt in range(3):
        mark = len(read_log().splitlines())
        # 每次只点一下，且重试间隔 > 320ms —— 两次落在双击判定窗内会变成"双击"
        tap(pet_xy)
        new, mark = wait_for(mark, "触摸: 按下", 2.0)
        joined = "\n".join(new)
        if "触摸: 按下" in joined:
            break
        B.log("第 %d 次点击没落到宠物上，重试" % (attempt + 1))
        time.sleep(0.7)
    # 单击是"抬手 180ms 后"才执行的，再等一拍把这一段收进来
    new2, mark = wait_for(mark, "单击", 1.5)
    joined += "\n" + "\n".join(new2)
    check("触摸到达窗口（按下）", "触摸: 按下" in joined,
          "" if "触摸: 按下" in joined else "窗口压根没收到事件：检查是否在屏幕外/被别的窗盖住")
    check("抬手事件完整", "触摸: 抬手" in joined)
    check("识别成单击", "单击" in joined,
          "" if "单击" in joined else "有按下有抬手但不是单击：手势被系统判成了滑动/CANCEL")

    # ---------------------------------------------------------------- D
    B.step("D. 横向拖宠物 —— 位置应该跟着走")
    joined = ""
    for attempt in range(3):
        mark = len(read_log().splitlines())
        x, y = pet_xy
        sh(["input", "swipe", str(x), str(y), str(max(60, x - 260)), str(y), "420"])
        new, mark = wait_for(mark, "拖动: 开始", 2.0)
        joined = "\n".join(new)
        if "拖动: 开始" in joined:
            break
        B.log("第 %d 次滑动没被识别成拖动，重试" % (attempt + 1))
        time.sleep(0.5)
    new2, mark = wait_for(mark, "拖动: 结束", 1.5)
    joined += "\n" + "\n".join(new2)
    check("手势被识别成拖动", "拖动: 开始" in joined,
          "" if "拖动: 开始" in joined else "没进拖动：可能起点落在系统手势热区，或被判成点击")
    end = re.search(r"拖动: 结束 锚点=\((-?\d+),(-?\d+)\)", joined)
    check("拖动结束（抬手存档）", end is not None)
    if end and pos:
        dx = int(end.group(1)) - pos[0]
        check("位移方向正确且量级合理", -300 < dx < -120, "锚点水平位移 %d px（手势 260 px）" % dx)

    # ---------------------------------------------------------------- E
    #
    # air 的诉求原话是"在软件内部设置好位置，退出软件之后就不能改变位置了" ——
    # A 证明了"能设"，这里证明"设完动不了"。测完必须把开关关回去，别把设备留在锁定态。
    B.step("E. 「锁定位置」打开后 —— 拖它应该纹丝不动")
    sh(["am", "start", "-n", ACT])
    time.sleep(2.5)
    sw_xy = switch_xy(scroll_to_text("锁定位置"), "锁定位置")
    if not sw_xy:
        check("面板里找到「锁定位置」开关", False, "uiautomator 里没定位到那个 Switch")
    else:
        check("开关生效（服务读到锁定位置=true）", toggle_until(sw_xy, "锁定位置=true"))

        sh(["input", "keyevent", "KEYCODE_HOME"])
        time.sleep(1.5)
        # 宠物被 D 拖到了新的锚点上。纵向没动过，所以 pet_xy 的 y 仍然成立，只换 x。
        dragged = re.search(
            r"拖动: 结束 锚点=\((-?\d+),(-?\d+)\)", "\n".join(read_log().splitlines()))
        body = (int(dragged.group(1)), pet_xy[1]) if dragged else pet_xy
        mark = len(read_log().splitlines())
        sh(["input", "swipe", str(body[0]), str(body[1]), str(max(60, body[0] - 240)),
            str(body[1]), "420"])
        new, mark = wait_for(mark, "拖动:", 2.5)
        joined = "\n".join(new)
        check("拖动被位置锁拦下", "被位置锁拦下" in joined,
              "" if "被位置锁拦下" in joined else "没拦住，锁形同虚设")
        check("锚点没变（真的没动）", "拖动: 结束" not in joined,
              "日志: %s" % " | ".join(l[-30:] for l in new if "拖动" in l))

        # 恢复：把开关关回去（别把设备留在锁定态）
        sh(["am", "start", "-n", ACT])
        time.sleep(2.5)
        sw_xy2 = switch_xy(scroll_to_text("锁定位置"), "锁定位置")
        if sw_xy2:
            check("开关已恢复为关（不把设备留在锁定态）",
                  toggle_until(sw_xy2, "锁定位置=false"))
        sh(["input", "keyevent", "KEYCODE_HOME"])

    B.step("结果")
    print("  通过 %d 项，失败 %d 项" % (len(_passed), len(_failed)))
    if _failed:
        print("  失败: %s" % ", ".join(_failed))
    print("\n--- dpet.log 尾部（判定依据，附上便于对照） ---")
    for line in read_log().splitlines()[-40:]:
        print("  " + line)
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
