# Android 手机版（`android-port/`）

把桌面版鲸鱼娘搬到 Android：一个前台服务挂两个悬浮窗，宠物飘在桌面上，
触摸能拖能点，状态机、气泡、音效、控制面板都齐。

**刻意不用 Gradle。** 构建链是手写的五步：

```
aapt2 link  →  kotlinc  →  d8  →  zipalign  →  apksigner
```

一轮约 10 秒，没有 daemon 冷启动、没有依赖解析、没有 `build.gradle` 里
看不完的配置。代价是**没有资源编译器** —— 所以整套 UI 是纯代码搭的：
零 `res/layout`、零 `res/drawable`、零 AndroidX。色板在 `Ui.kt`，控件用
`TextView` / `Button` / `SeekBar` / `Switch` 现拼。这套做法沿用自
「小米表盘自定义工具手机版」，那边同样是在手工链上跑起来的。

## 目录

| 路径 | 是什么 |
|---|---|
| `app/` | **正式版**。包名 `dpet.app`，产物 `app/build/pet.apk` |
| `bench/` | 基准测试版。包名 `dpet.benchui`，产物 `bench/build/petbench.apk` |
| `core/` | 跨端共享的纯逻辑：`Motion.kt`（动效解释器）、`MiniJson.kt` |
| `verify/` | 跨端动效一致性校验（Python 参考实现 ↔ Kotlin） |
| `tools/` | 自带的 kotlinc（已 gitignore，需要时从 zip 解压） |

`app/src/dpet/app/` 是正式版的全部代码：

| 文件 | 职责 |
|---|---|
| `App.kt` | 版本常量 + `PanelState`（面板开关的同进程状态） |
| `OverlayService.kt` | 前台服务，宿主宠物窗与气泡窗，帧驱动、广播、手势分发 |
| `PetView.kt` | 宠物本体：绘制变换链 + 拖动/单击/双击/长按 |
| `PetState.kt` | 状态机：状态切换、自发小动作、眨眼、犯困分层 |
| `Pack.kt` | 内容包：读 `content/actions.json` + 解码 webp，按目标高度重缩放 |
| `BubbleView.kt` | 气泡：逐字符折行 + 体型轮廓描边 + 尾巴指向 |
| `Sfx.kt` | 音效：SoundPool 预载 + 110ms 重叠门 + 失败静默降级 |
| `Lines.kt` | 台词库（`src/lines.py` 的 Kotlin 副本） |
| `MainActivity.kt` | 控制面板（纯代码 UI） |
| `PetConfig.kt` | SharedPreferences 配置读写 |
| `Ui.kt` | 纯代码 UI 工具箱：色板、dp/sp、圆角背景、常用控件 |
| `DLog.kt` | 落盘日志 + 崩溃捕获（原因见「设备坑」） |

## 构建 / 运行

```bash
cd android-port

python build_app.py              # 构建正式版 + 装上设备
python build_app.py --no-install # 只构建
python build_app.py --run        # 装上后直接打开控制面板
python build_app.py --assets-only# 只拼 assets（排查内容包问题时用）

python build_poc.py --no-install # 构建基准测试版（bench/）
python build_bench.py            # app_process + dex jar 那条独立路径
```

`dpetbuild.py` 是公共链：`preflight / link_resources / compile_kotlin / dex /
pack / ensure_keystore / sign_and_align / build / install_with_ui_fallback`。
`build_app.py` 与 `build_poc.py` 都只是给它配参数。

内容包（`assets/`）由 `prepare_assets()` 现拼：`content/actions.json` +
`assets/pet/*.webp` + `assets/sfx/*.wav`。桌面端的 `assets/pet/manifest.json`
**不进包** —— 那是给发布流程核对素材用的，运行时不需要。

装完会自动 `appops set dpet.app SYSTEM_ALERT_WINDOW allow` 并授予通知权限：
重装会把这两项重置回未授予（`appops` 记录跟着包一起被清），每轮迭代都手动开
一次太蠢。这是开发脚本的行为，分发出去别人仍然要自己去系统设置里点。

## 架构：两个窗口

比桌面版麻烦的地方在**触摸**。

桌面版靠 `QRegion` 掩码把落在透明像素上的点击透给下层窗口。Android 没有对应
机制：overlay 窗口要么整个收触摸，要么整个不收。于是拆成两个窗口：

| 窗口 | 尺寸 | 触摸 | 说明 |
|---|---|---|---|
| 宠物窗 | **严格等于**「当前帧 + 2×`pad`」 | 可触摸 | 帧在窗内恒为 `(pad, pad)` |
| 气泡窗 | 宽得多（`WRAP_CONTENT`，上限 240dp） | 永远 `FLAG_NOT_TOUCHABLE` | 只负责显示 |

宠物窗尺寸刻意**不取所有帧的最大包围盒**。whale 帧有 724px 宽，而 idle 只有
380px —— 用最大包围盒会让 idle 时代周围多出一大圈透明区域，白吃掉触摸。

配套的是**脚底锚点**：窗口左上角按 `(anchorX, anchorY)` 摆，帧尺寸变化时窗口
边缘伸缩而宠物在屏幕上纹丝不动。`placeByAnchor()` 在钳制到屏幕内之后**会把
钳制结果反推回写 `anchorX/anchorY`** —— 否则把宠物拖到屏幕边缘再换帧，它会跳
出去。

### 面板穿透

控制面板一开，宠物窗必须临时变成 `FLAG_NOT_TOUCHABLE`，否则面板上落在宠物
覆盖区域的那一块控件收不到触摸。实测第一版用广播通知服务切换，**失效**：
服务刚被拉起、接收器还没注册的那段空档里广播会丢。现在走同进程静态对象
`PanelState.observe()`，注册时立刻回调当前值：

```kotlin
if (cfg.locked || panelOpen) addFlags(FLAG_NOT_TOUCHABLE) else clearFlags(FLAG_NOT_TOUCHABLE)
```

## 移植纪律（改 `core/` 前必读）

动效曲线是**数据**（`content/actions.json` 的 `motions` 段），引擎只解释执行。
`Motion.kt` 与 Python 的 `src/motion.py` 必须逐位一致（`abs_tol=0`），所以：

- **运算顺序逐字保持。** 交换率在浮点下不成立。
- **用 `Math.rint`，不是 `Math.round`。** 前者是银行家舍入，与 Python 的
  `round()` 一致；后者是"四舍五入远离零"，会在 `.5` 处分叉。
- **手写 `pyMod`。** Kotlin 的 `%` 对负数返回负值，Python 的返回非负。
- **`motion.CYCLE` / `motion.VISUAL_SCALE` 不能删。** 它们看着像模块级死常量，
  实际是跨语言校验链路的取数口（`verify/gen_python_ref.py`、`verify/spy_sin.py`
  都按它们遍历素材）。

改完跑：

```bash
python verify/run_verify.py
```

## 设备坑（都是实测踩出来的）

- **HyperOS 拦 `adb install`。** 报 `INSTALL_FAILED_USER_RESTRICTED`。
  `settings put adb_install_need_confirm`、`pm install`、
  `install-create/write/commit`、`--no-streaming`、指定 installer 包名
  —— 全试过，全拦。可靠绕法：`adb push` 到 `/sdcard/Download/` +
  `am start -a android.intent.action.INSTALL_PACKAGE`（这条不受管辖）+
  从 `uiautomator dump` 取按钮坐标 + `input tap`。`dpetbuild.py` 里
  `install_with_ui_fallback()` 走的就是这条路，同时也支持直接 `adb install`
  成功的情况（同一台设备不同时候行为会变）。
- **`logcat` 在测试机上完全不可用。** `logd not running`，设备侧直接执行也一样。
  所以自建 `DLog`：同时写 `Android/data/dpet.app/files/dpet.log`，超过 256KB
  截断保留后半，并装未捕获异常处理器。
- **重装会重置 `appops SYSTEM_ALERT_WINDOW`**，宠物就不出现了（服务正常在跑，
  只是没窗口）。`build_app.py` 装完自动补授。
- **`adb push /data/local/tmp/...` 会被 Git Bash 改写成本地路径**，
  要加 `MSYS_NO_PATHCONV=1`。`uiautomator dump` / `screencap` 的远端路径同理。
- **`input tap` 偶发不生效**（连点两次更可靠）；`input tap` 与
  `input touchscreen tap` 语义不同；双击用
  `input "touchscreen tap X Y; touchscreen tap X Y"` 在单次 shell 里串联。
- **测试解锁链路用 `adb shell wm dismiss-keyguard`。** 滑动解锁（`input swipe`）
  对密码锁屏无效；`am broadcast -a USER_PRESENT` 会被拒（protected broadcast）；
  `settings put secure lockscreen.disabled 1` 在 HyperOS 上**不生效**
  （keyguard 照样 `isKeyguardShowing=true`）。

## 关于 `ACTION_USER_PRESENT`

"亮屏只是瞄一眼时间，不该说话；解锁才算人回来了" —— 这个判断不能只靠一个
广播，各家 ROM 行为不一，本机实测就有两种：

- 有密码锁屏：亮屏时 keyguard 在，`USER_PRESENT` 要等真正解锁才发。
- 把锁屏整个关掉之后：**这个广播根本不发**（没有 keyguard 可解）。

所以走双保险：`onScreenOn()` 只把画面叫醒（置 `wokeFromSleep`），帧循环里
再拿 `KeyguardManager.isKeyguardLocked` 兜一次底。两条路谁先到谁兑现，
`onUserPresent()` 内部清标志，不会重复问候。

## 验证状态（2026-10-15，Redmi Note 11 / HyperOS / Android 17）

真机跑通：

- 悬浮窗显示、单击随机反应、双击、拖动、长按开面板
- 面板穿透（开面板时宠物窗带 `NOT_TOUCHABLE`，关掉即恢复）
- 大小滑块真实拖动生效（306 dp → 167 dp，窗口随之 719×936 → 502×521）
- 四个快捷动作（说句话 / 敲键盘 / 干饭 / 变条鱼）—— 状态 + 气泡 + 音效齐全
- 灭屏 → `sleep`，亮屏 → `idle`，解锁 → 问候（含 `wm dismiss-keyguard` 验证）
- 内容包加载（v1 · 10 帧 · 8 状态）、15 条音效预载

已知限制：

- **APK 1.53 MB，dex 里含未裁剪的 kotlin-stdlib。** 本机 SDK 的
  `build-tools/37.0.0` 只有 `d8.bat`，**没有 `r8.bat`**，而
  `d8 --release` 不做 tree shaking。表盘工具那边过 R8 full mode 后
  stdlib 从 1108 个类压到 0、省 2 MB —— 装上 r8 就能把这里降到约 780 KB
  （剩下的基本都是素材）。
- 手机版**没有远端内容更新**，只有内置 `content/`。`PetState.refreshPools()`
  留了口子但当前没有调用方。
- 只在一台设备（Android 17 / HyperOS）上验证过。其他 ROM 的悬浮窗行为、
  广播时序、安装拦截策略都可能有差异。
