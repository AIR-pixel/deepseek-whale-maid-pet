<!-- GH-ONLY:START 这一段只在 GitHub 上显示（横幅/截图/下载指引）。
     打包脚本会把 GH-ONLY 区间连同标记整段删掉，所以包内的 README 不会出现
     ./docs/ 这种包里不存在的相对路径。改这里不用同步改别处。 -->

<img src="docs/banner.png" alt="DeepSeek 鲸鱼娘 · 桌面宠物" width="100%">

**一只住在桌面右下角的女仆鲸鱼娘。** 轻量 · 纯本地 · 无联网 · 无后台服务。

10 套独立动效 · 15 条程序合成音效 · 59 条台词 · 22 MB 免安装。

| 想怎么用 | 下载哪个 |
|---|---|
| **马上用，什么都不装** | [`DeepSeek-WhaleMaidPet_1.0.0_selfcontained.zip`](https://github.com/AIR-pixel/deepseek-whale-maid-pet/releases/latest/download/DeepSeek-WhaleMaidPet_1.0.0_selfcontained.zip) · 21.8 MB |
| 机器上已有 Python 3.9+ | [`DeepSeek-WhaleMaidPet_1.0.0_source.zip`](https://github.com/AIR-pixel/deepseek-whale-maid-pet/releases/latest/download/DeepSeek-WhaleMaidPet_1.0.0_source.zip) · 727 KB |
| 读代码 / 自己改 | `git clone` 本仓库，见下面「[运行](#运行)」 |

> 附件名是 ASCII 的：GitHub 会把 Release 附件的 name 里**非 ASCII 字符替换成 `.`**
> （`DeepSeek鲸鱼娘桌宠_自包含_20260926.zip` 传上去会变成 `DeepSeek._._20260926.zip`），
> 所以这里换了英文名。**解压出来的目录名仍是中文** `DeepSeek鲸鱼娘桌宠`。
> 全部版本见 [Releases](https://github.com/AIR-pixel/deepseek-whale-maid-pet/releases)。

> 同人作品，**非商用**。代码 MIT、立绘素材 CC BY-NC-SA 4.0 —— 见「[署名与许可](#署名与许可)」。

## 它动起来是什么样

![动效循环](docs/motion.gif)

| 全部 10 个状态 | 各状态动效矩阵 |
|---|---|
| ![状态](docs/states.png) | ![动效矩阵](docs/motion-matrix.png) |

尺寸阶梯（80–560 每档实测）与音效波形：`docs/size-ladder.png`、`docs/sfx-waveform.png`。

<!-- GH-ONLY:END -->

# DeepSeek 鲸鱼娘 · 桌面宠物

一只住在桌面右下角的女仆鲸鱼娘。轻量、纯本地、无联网、无后台服务。

体积构成：立绘 562 KB + 音效 149 KB + 代码约 55 KB。

## 运行

双击 **`启动桌宠.bat`**。

依赖：Python 3.9+ 与 `pip install pyqt5`（音效用 `PyQt5.QtMultimedia`，
属于 pyqt5 的一部分，无需额外安装）。启动器按这个顺序找解释器：

1. **`DPET_PYW` 环境变量** —— 显式指定，优先级最高（开发/验收用）
2. 同目录 **`runtime\pythonw.exe`** —— 塞一个便携 Python 进去就能完全自包含
3. PATH 上的 **`pythonw` → `python`**
4. **`py -3`** 启动器 —— 取它解释器旁边的 `pythonw.exe`

找到后**预检 `import PyQt5`**，缺库时打印当前用的是哪个解释器并给出安装命令，
不会静默失败。若某台机器上 QtMultimedia 后端不可用，音效菜单项会**置灰并给出原因**，
桌宠照常运行。

> 启动器是**纯 ASCII + CRLF** 写的：cmd 按 GBK 解析 UTF-8 中文会字节错位，
> 导致一堆"不是内部或外部命令"。改这个 `.bat` 时**不要往里写中文**。

## 交互

| 操作 | 效果 |
|---|---|
| 左键拖拽 | 移动位置（自动记忆） |
| 单击 | 随机反应：开心 / 蒙眼害羞 / 变回鲸鱼原型 / 干饭 / 说句话 |
| 双击 | 蹦一下并吐槽 |
| 滚轮 | 缩放大小（**80–560**；低于 240 时步长自动降到 10px，方便微调小尺寸） |
| 右键 | 功能菜单 |
| 托盘图标 | 单击显示/隐藏，右键菜单 |

右键菜单可调：大小（迷你 90 / 很小 130 / 小 190 / 标准 280 / 大 380 / 很大 460 / 超大 560）、
透明度、始终置顶、气泡开关、**交互音效开关 + 音量 + 试听**、喝水提醒、久坐提醒、
开机自启、回到右下角。

> 尺寸是**逻辑像素**。在 200% 缩放的屏幕上，"迷你 90" 实际占屏幕高度约 11%。
> 立绘按 2 倍分辨率渲染再由 Qt 缩放（超采样），所以调小不会糊。

## 音效

**15 条交互反馈音，共 149 KB**，全部由 `tools/make_sfx.py` **程序合成**——
不含任何采样素材，所以没有版权问题，风格不对改几个数字重跑即可。

| 时机 | 音 | 时机 | 音 |
|---|---|---|---|
| 启动问候 | `hello` 上行四音 | 点击 → 开心 | `happy` 大三和弦琶音 |
| 双击蹦跳 | `hop` E6→B6 | 点击 → 害羞 | `shy` 下滑小两度 + 颤音 |
| 拖拽拿起 / 放下 | `grab` / `drop` | 点击 → 变鲸鱼 | `whale` 下潜 + 气泡 |
| 滚轮放大 / 缩小 | `zoom_up` / `zoom_down` | 点击 → 干饭 | `eat` 两下咀嚼 |
| 气泡弹出 | `pop` 极短"啵" | 从打盹被叫醒 | `wake` 上行两音 |
| 单击兜底 / 菜单 | `click` | 开始干活 | `work` 键帽咔哒 |
| | | 喝水 / 久坐提醒 | `remind` 叮咚两下 |

三个实现要点：

- **`QSoundEffect` 是异步加载的**，未 Ready 时 `play()` 直接无效（不报错）。
  启动时一次性预载并等就绪（实测 132ms），否则"第一次点击没声音"。
- **全局最小间隔 110ms** 挡掉几乎同时触发的第二条。点击时状态音和气泡音会挨着触发，
  没有这道门就会叠成一声怪音。同一 cue 连打不用防抖——`QSoundEffect` 自己会合并。
- **自发小动作默认不出声**（`deepseek_pet.py` 的 `AUTO_CUE`）。需求是"交互反馈"，
  每几十秒自己响一声会变成噪音。想要"有生命感"把 `AUTO_CUE` 改成 `True`。

重新生成：`python tools/make_sfx.py`。改风格就调 `chime()` 的泛音比、滑音方向、
`env()` 的衰减曲线，以及 `CUES` 里每条的目标峰值。

## 动效

每个状态都有独立的运动曲线（`src/motion.py`），全部由**同一张立绘实时变换**得到，
帧间零漂移——不会像 AI 生成序列帧那样五官乱跳、描边闪烁。

| 状态 | 动效 |
|---|---|
| 待机 | 呼吸起伏（约 3.6s 一个来回）+ 随机眨眼 |
| 工作 | 敲键盘的双频脉冲律动 + 轻微左右摇 |
| 干饭 | 咀嚼节奏（约 1s 一回）+ 小幅点头 |
| 犯困 | 缓慢低头 → 猛地抬头，周期 3.4s |
| 睡觉 | 深呼吸，幅度大于待机 |
| 鲸鱼 | 水中漂浮：左右漂 + 上下浮 + 轻微摇摆 |
| 蒙眼 | 两个频率叠加的慌张发抖 |
| 开心 | 蹲下蓄力 → 跳起 → 落地缓冲 |

三个实现要点：

- 变换锚点是**脚底中心**——呼吸时脚不动、蹦跳时整个人离地、压扁时从脚底往上缩，
  不会出现"角色在窗口里乱飘"的廉价感。
- 幅度按 `实际高度 / 280` 等比缩放，滚轮能到的 **80–560 每一档都实测过不越界**，
  不会出现放下"超大"后跳到一半被窗口裁掉。
- 但等比缩放有**下限** `SCALE_MIN = 0.5`：再小就不继续缩了，否则"迷你 90"的呼吸
  只剩 1px 出头，肉眼等于静止。窗口边距有固定的 +12px 底数，所以钳住下限也不会越界。
- 窗口为动效预留边距（`12 + 高度 × 0.042`），遮罩用 8 方向膨胀，
  保证跳到最高点、摇到最歪时仍然点得到角色。

调手感只改 `src/motion.py`，曲线数值的含义是"280px 高度下的像素幅度"。
`VISUAL_SCALE` 用于配平各素材的视觉体量（横躺的鲸鱼本来会显得比别人大一圈）。

## 它会自己做的事

- **时间问候**：按凌晨/早/午/下午/晚/深夜切换开场白
- **空闲感知**：读取系统键鼠空闲时间，超过 3 分钟抱枕犯困，超过 10 分钟睡着；你一回来就醒
- **自发小动作**：待机时会自己变回鲸鱼、开心一下或敲会儿键盘
- **台词**：59 条，围绕"聪明但懒、傲娇、爱吃白饭"的官方+社区设定

## 素材

10 张透明 WebP（562 KB）+ 15 条合成音效 WAV（149 KB）。图片由
`tools/prepare_assets.py` 从原始素材自动处理（底色判别 → 抠图 → 去背景色污染 →
清理格间残留 → 裁边 → LANCZOS 降采样 → WebP）；音效见上面「音效」一节。

| 帧 | 用途 | 尺寸 |
|---|---|---|
| `idle_open` / `idle_blink` | 待机睁眼 / 闭眼 | 380×512 |
| `work_keypress` / `work_desk` | 敲键盘 / 趴桌敲键盘 | 491×512 / 556×512 |
| `eat` | 干饭 | 403×512 |
| `doze` / `sleep` | 抱枕犯困 / 睡觉 | 399×512 / 464×512 |
| `whale` | 鲸鱼原型 | 724×512 |
| `blindfold` / `happy` | 蒙眼害羞 / 开心 | 499×512 |

## 项目结构

```
deepseek-pet/
├── 启动桌宠.bat
├── config.json              # 位置/大小/开关，运行时自动生成（不入库）
├── src/
│   ├── deepseek_pet.py      # 主程序
│   ├── motion.py            # 每个状态的动效曲线
│   ├── sfx.py               # 音效播放（QSoundEffect 预载 + 全局间隔）
│   └── lines.py             # 台词库
├── assets/
│   ├── pet/                 # 处理后的立绘素材 + manifest.json
│   └── sfx/                 # 合成音效 WAV（生成物，可重建）
├── docs/                    # README 里的横幅与预览图
├── dist/                    # 打包产物（zip，不入库 → 见 Release）
├── tools/
│   ├── prepare_assets.py    # 素材处理流水线
│   ├── make_sfx.py          # 音效合成（正弦/三角波 + 包络，无采样素材）
│   ├── preview_motion.py    # 生成动效对比图 / 循环 GIF / 尺寸阶梯图
│   ├── preview_sfx.py       # 生成音效波形总览图
│   ├── make_banner.py       # 用真实立绘生成 README 横幅
│   ├── smoke_test.py        # 无头冒烟测试（15 组 61 项）
│   ├── verify_live.py       # 真机验证：起进程 → 按窗口句柄截图 → 帧间比对
│   ├── pe_deps.py           # 解析 PE 导入表算 DLL 传递闭包（校验精简清单）
│   ├── build_package.py     # 打源码便携包（zip）+ 五项自检
│   ├── build_runtime.py     # 打自包含便携包（含精简 Python + PyQt5）+ 八项自检
│   └── accept_package.py    # 端到端验收：解包 → 用包内启动器真跑起来
├── LICENSE                  # 代码许可：MIT
└── LICENSE-ASSETS           # 立绘素材许可：CC BY-NC-SA 4.0
```

> 原始素材 `ref_assets/` 与清理暂存目录不入库（`.gitignore` 已挡）。
> 它们只在重跑素材流水线时有用，运行时用不到。

> 冒烟测试与预览脚本都会调 `_set_height()` / `_set_opacity()`，而这两个方法内部会写盘。
> 它们都把 `CONFIG_PATH` 指向临时文件，**不会覆盖你自己调的 config.json**。
> 冒烟测试还会交叉核对"代码里引用的 cue 名都有对应 wav"——能自动抓住
> "加了新音效但忘了重跑 `make_sfx.py`"这类错误。

```bash
python tools/smoke_test.py              # 改完代码先跑这个
python tools/preview_motion.py          # 只想要动效图 / 尺寸阶梯图
python tools/verify_live.py             # 断言"真机上真的在动"
python tools/verify_live.py --height 90 # 指定尺寸验证（用临时配置，不动你的设置）
python tools/build_package.py           # 打源码便携包到 dist/（727 KB）
python tools/build_runtime.py           # 打自包含便携包到 dist/（约 22 MB）
python tools/accept_package.py          # 解包 → 用包内启动器真跑一遍
python tools/pe_deps.py                 # 只算 Qt 的 DLL 硬依赖闭包
```

> `verify_live.py` 与 `accept_package.py` 都按「启动前后窗口集合做差」定位自己的窗口。
> 不能只按标题取第一个（你自己可能也开着一个），也不能按 PID 匹配（venv 的
> `Scripts/python.exe` 会再起子进程持有窗口，父子 PID 不一致）。

## 打包 / 分发

两个包，按收件人是谁来挑：

| 包 | 体积 | 对方要做什么 |
|---|---|---|
| `DeepSeek鲸鱼娘桌宠_<日期>.zip` | **727 KB** | 装 Python 3.9+ 和 `pip install pyqt5` |
| `DeepSeek鲸鱼娘桌宠_自包含_<日期>.zip` | **约 22 MB** | **什么都不用装**，解压双击 |

### 源码便携包（`tools/build_package.py`）

只装**运行需要的东西**：`src/`、`assets/`（立绘 + 音效）、`config.json`、`启动桌宠.bat`、`README.md`。
预览图、原始素材 `ref_assets/`、开发工具 `tools/` 都不进包。

### 自包含便携包（`tools/build_runtime.py`）

多一个 `runtime/`：把精简过的 CPython + 精简过的 PyQt5 塞进去，启动器会优先用它。
对方解压双击即可，不装任何东西。体积构成：

| | 精简前 | 精简后 |
|---|---|---|
| PyQt5 | 142 MB | **36 MB** |
| CPython | 48 MB | **21 MB** |
| 解压后合计 | | **58 MB** → zip **22 MB** |

裁剪原则是"只留真正调到的"：Qt 只留 Core/Gui/Widgets/Multimedia/Network、WebP 图片插件、
音频后端（dsengine + wasapi）、Windows 平台插件；解释器丢掉 pip/setuptools、include/libs、
ensurepip/venv/pydoc_data、openssl（光 libcrypto 就 7.6 MB）、sqlite3、`_test*` 系列。

### 打完立刻自检

源码包做五项，自包含包在此之上再加三项（A–E 全过才判定可用）：

| # | 校验 | 抓的是什么错 |
|---|---|---|
| 1 | 必需文件齐全 | 漏打包某个源文件 |
| 2 | 贴图/音效条数对得上 manifest、目录 | 素材改名后 manifest 没同步 |
| 3 | 启动器仍是纯 ASCII + CRLF | 改 bat 时手滑写进中文 / LF |
| 4 | 包内 `config.json` 不带本机窗口坐标 | 把你屏幕上的坐标发给别人 |
| 5 | **解包出来的副本**能加载素材、切全部状态、音效就绪 | 硬编码路径、相对路径失效 |
| A | `runtime/` 关键文件齐全 | 漏拷 pythonw / Qt DLL / WebP 插件 |
| B | **包内解释器**能 import 全部用到的 PyQt5 模块 | 漏拷 `.pyd`（如 QtMultimedia 会隐式要 QtNetwork） |
| C | **包内解释器**跑一遍完整自检 | 上面第 5 项用本机解释器跑等于没测 |
| D | 包内无机主路径残留 | 把 `C:\Users\<你>` 发给别人 |
| E | 精简 Qt 清单覆盖 PE 硬依赖闭包 | 漏拷 DLL，在别人机器上启动即挂且**没有报错** |

第 5 项和第 C 项的关键：**在解包出来的临时目录里跑**，而不是原目录。原目录跑永远发现不了
绝对路径依赖。E 项由 `tools/pe_deps.py` 解析 PE 导入表算传递闭包得出，不靠人眼核对——
它当场就抓出了漏掉的 `msvcp140_1.dll`（本机装了 VC++ 运行库所以没暴露）。

`python tools/accept_package.py` 做最后一道：**真的把 zip 解开、用包里自带的启动器跑起来**，
轮询确认窗口出现且尺寸正常，然后关掉。包里自带 `runtime/` 时它会刻意**不注入** `DPET_PYW`，
让包内解释器真的被验证到。

### 三个踩过的坑

- **`config.json` 用默认值写进包**，不是本机那份。本机那份存着窗口坐标（如 `x=1160`），
  虽然启动时会夹回屏幕内，但从默认右下角开始更自然。
- **验收不能 `capture_output`**。启动器里 `start ""` 会派生一个脱离的桌宠进程，
  它**继承管道句柄**，父进程会一直等 EOF 直到桌宠退出，命令挂死。
  必须 `DEVNULL` + 超时，而且 `stdin` 也得是 `DEVNULL`——失败分支末尾有 `pause`。
- **包内非 ASCII 文件名要带 UTF-8 标志位**（`0x800`）。`zipfile` 会自动置，用别的方式打 zip
  得自己确认，否则某些解压工具会给出乱码文件名。

### 中文路径：Qt 会在这里静默翻车（已修）

**路径里只要有一个非 ASCII 字符，Qt 就找不到自己的插件。** 原因是 Qt 推导 `Qt5Core.dll`
所在目录时走的是窄字符 API，`DeepSeek鲸鱼娘桌宠` 会被算成一串 `?`，于是
`QCoreApplication.libraryPaths()` 返回**空** → 找不到平台插件 → Qt 弹一个**模态错误框然后卡住**。
症状是"双击没反应"，没有崩溃、没有 stderr 日志，极难排查。`qt.conf` 也救不了（它同样要经
Qt 的路径解析）。

修法在 `src/deepseek_pet.py` 的 `pin_qt_plugins()`：不让 Qt 自己推，直接用 Python 的
Unicode 路径从 PyQt5 包的位置手动 `addLibraryPath()`。Python 的 str→QString 走宽字符，
不受影响；也比设 `QT_PLUGIN_PATH` 环境变量更稳（那个在非中文区域设置下会再翻一次车）。
这个修复让源码包和自包含包在中文目录下都能正常运行，验收脚本里已把它当回归测试
（解包目录就是中文的）。

> 打包用哪个解释器跑不影响产物（包里不含 Python）。
> 想手动指定：`python tools/accept_package.py --pyw <pythonw.exe 路径>`；
> 想强制用本机解释器测：加 `--use-override`。

## 自定义

- **加台词**：编辑 `src/lines.py` 里对应的列表即可，重启生效。
- **换素材**：把图片放进 `assets/pet/`，在 `manifest.json` 登记，并在
  `src/deepseek_pet.py` 的 `STATES` 里引用名字。
- **改默认大小**：`STATES` 上方的 `DEFAULT_CFG["height"]`。
- **调空闲阈值**：`_tick()` 中 `idle > 600`（睡觉）/ `idle > 180`（犯困）。
- **调音效风格**：`tools/make_sfx.py`——泛音比、滑音方向、衰减曲线、每条的目标峰值；
  改完重跑一次即可。想让自发小动作也出声：`deepseek_pet.py` 的 `AUTO_CUE = True`。
- **改某次交互配什么音**：`deepseek_pet.py` 的 `STATE_CUE`（状态音）与各交互点的
  `sfx.play(...)` / `_say(..., cue=...)`。`cue=None` 表示这次不出声。
- **换播放后端**：只改 `src/sfx.py`。目前用 `QSoundEffect`（带音量、可叠加）；
  若某机器后端有问题，`winsound` + `SND_MEMORY` 是零依赖的退路，代价是没有音量控制。

## 署名与许可

角色形象为社区二创「女仆鲸鱼娘」，**非官方同人作品，请勿商用**。

### 分拆授权

代码与素材**不能同证**，所以分开授权：

| 范围 | 许可证 | 文件 |
|---|---|---|
| `src/` · `tools/` · `启动桌宠.bat` | **MIT** | [LICENSE](LICENSE) |
| `assets/sfx/`（纯程序合成，无采样素材） | **MIT** | [LICENSE](LICENSE) |
| `assets/pet/` · `docs/`（立绘及其派生图） | **CC BY-NC-SA 4.0** | [LICENSE-ASSETS](LICENSE-ASSETS) |

为什么必须拆：角色依 CC BY-NC-SA 4.0 开放二创，该许可的 **ShareAlike** 条款要求
派生作品以相同方式共享——不能被 MIT 覆盖。所以代码走宽松许可，立绘保持原许可。
**用立绘做二创时请照抄 `LICENSE-ASSETS` 里的完整署名链**，并同样以
CC BY-NC-SA 4.0 发布。

### 署名链

- 原创角色 **溟月** — 上善无形（2025.06），以 **CC BY-NC-SA 4.0** 开放二创
- 女仆装与 DeepSeek 元素二创 — ZipZipPipe（2026.04）
- 桌宠立绘素材与本项目参考 — [keleus/deepseek-pet](https://github.com/keleus/deepseek-pet)（MIT，仅其代码部分）
- 桌宠程序与素材再加工 — air / AIR-pixel（2026.09）

DeepSeek 及相关标识归杭州深度求索人工智能基础技术研究有限公司所有。
本项目与 DeepSeek 官方**无任何关联**，未获其授权或背书。
