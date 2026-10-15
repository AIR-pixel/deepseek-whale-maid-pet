package dpet.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.hardware.display.DisplayManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.DisplayMetrics
import android.view.Display
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Switch
import android.widget.TextView
import dpet.core.MiniJson

/**
 * 控制面板：开关桌宠、权限引导、外观与行为设置、快捷动作。
 *
 * 整套界面**纯代码构建**（不引 AndroidX、不放 res/layout）。构建链是手工的
 * aapt2→kotlinc→d8，没有资源编译器帮你把 XML 编成二进制，用布局文件反而要
 * 自己处理 res 目录 —— 几百行命令式建 View 换来的是"改一行、10 秒后装机"。
 * 这套做法在小米表盘工具手机版上已经跑过一遍，APK 从 2.1MB 压到 54KB（过 R8）。
 *
 * 与宠物互动的常规路径**不经过这个 Activity**：单击/双击/拖拽都在悬浮窗里就地响应。
 * 面板只在"长按宠物"或"点通知"时打开，用来做一次性的设置。
 *
 * 例外是**位置**。面板在前台时宠物窗口是 `FLAG_NOT_TOUCHABLE` 的（见 [PanelState]），
 * 也就是"面板开着的时候宠物点不动"—— 这是 overlay 永远画在 Activity 之上的必然结果，
 * 不是 bug。所以位置必须能从这里改，见 buildUi 里的"位置"卡片。
 */
class MainActivity : Activity() {

    private lateinit var cfg: PetConfig

    private lateinit var statusDot: View
    private lateinit var statusTitle: TextView
    private lateinit var statusSub: TextView
    private lateinit var toggleBtn: Button
    private lateinit var permBox: LinearLayout
    private lateinit var shortcutLabel: TextView
    private lateinit var shortcutBox: LinearLayout
    private lateinit var sizeRow: LinearLayout
    private lateinit var opRow: LinearLayout
    private lateinit var contentInfo: TextView

    private var sizeValue: TextView? = null
    private var opValue: TextView? = null
    private var posXValue: TextView? = null
    private var posYValue: TextView? = null
    private var posXBar: SeekBar? = null
    private var posYBar: SeekBar? = null

    private val density: Float get() = resources.displayMetrics.density

    private fun dp(v: Int) = Math.round(v * density)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        DLog.init(this)
        cfg = PetConfig(this)

        window.statusBarColor = Ui.BG
        window.navigationBarColor = Ui.BG

        buildUi()
    }

    override fun onResume() {
        super.onResume()
        // 面板在前台时让宠物临时"触摸穿透"，否则它飘在滑块上面会把触摸全吃掉。
        // 用同进程静态状态而不是广播 —— 广播会在"服务刚被拉起、接收器还没注册"
        // 的空档里丢掉，见 PanelState 的注释。
        PanelState.set(true)
        // 桌宠本该在跑却不在（被系统回收过）就顺手拉起来 —— 用户不必自己去点一次开启
        if (cfg.enabled && Settings.canDrawOverlays(this)) ensureService()
        refresh()
    }

    override fun onPause() {
        super.onPause()
        PanelState.set(false)
    }

    // ------------------------------------------------------------ 界面

    private fun buildUi() {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(Ui.BG)
            isFillViewport = true
        }
        val col = linear(paddingDp = 0)
        col.setPadding(dp(18), dp(22), dp(18), dp(48))
        scroll.addView(col)

        // ---------- 顶部：桌宠开关
        val head = linear(bg = Ui.CARD, paddingDp = 16)
        val headRow = linear(vertical = false)
        statusDot = View(this).apply {
            layoutParams = LinearLayout.LayoutParams(dp(9), dp(9)).also {
                it.gravity = Gravity.CENTER_VERTICAL
                it.rightMargin = dp(9)
            }
            background = roundBg(Ui.TEXT_DIM, 5f)
        }
        headRow.addView(statusDot)
        val headText = linear()
        headText.layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        statusTitle = textView("桌宠", 17f, Ui.TEXT, bold = true)
        statusSub = textView("", 12.5f, Ui.TEXT_DIM)
        headText.addView(statusTitle)
        headText.addView(statusSub)
        headRow.addView(headText)
        head.addView(headRow)

        toggleBtn = Button(this).apply {
            textSize = 15f
            setTextColor(Color.WHITE)
            isAllCaps = false
            background = roundBg(Ui.ACCENT, 12f)
            setOnClickListener { if (cfg.enabled) stopPet() else startPet() }
        }
        val tlp = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
        )
        tlp.topMargin = dp(14)
        toggleBtn.layoutParams = tlp
        head.addView(toggleBtn)
        col.addView(head)
        marginBottom(head, 14)

        // ---------- 权限引导（没授权时才显示）
        permBox = linear(bg = Ui.CARD, paddingDp = 15)
        val permTitle = textView("需要「显示在其他应用上层」权限", 14.5f, Ui.WARN, bold = true)
        permBox.addView(permTitle)
        val permSub = textView(
            "系统弹出的是「后台弹出界面 / 悬浮窗」开关，打开它桌宠才能浮在桌面上。" +
                "国产 ROM 还常另有一个同名开关在「应用管理 → 权限」里。",
            12f, Ui.TEXT_DIM
        )
        permSub.setPadding(0, dp(7), 0, 0)
        permBox.addView(permSub)
        val permBtn = Button(this).apply {
            text = "去授权"
            textSize = 14f
            setTextColor(Color.WHITE)
            isAllCaps = false
            background = roundBg(Ui.ACCENT, 11f)
            setOnClickListener { openOverlaySettings() }
        }
        val plp = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
        )
        plp.topMargin = dp(12)
        permBtn.layoutParams = plp
        permBox.addView(permBtn)
        col.addView(permBox)
        marginBottom(permBox, 14)

        // ---------- 位置
        //
        // 这一块是**必需品不是锦上添花**：面板在前台时宠物窗口是 `FLAG_NOT_TOUCHABLE`
        // （overlay 永远盖在 Activity 之上，窗口只要还吃触摸，它压住的那一块控件就全废），
        // 所以"面板开着的时候"宠物一定是点不动的。用户想在这时给它挪个地方，只能靠这里。
        // 早先面板里没有这一块，用户对着一个浮在设置页上、点也点不动的宠物，
        // 得出的结论只能是"这软件坏了"。
        col.addView(sectionLabel("位置"))
        val posCard = linear(bg = Ui.CARD, paddingDp = 14)
        posCard.addView(
            textView(
                "先挑个角落，再用两根滑块微调。改完立刻生效，退出面板后位置就定在这儿了。" +
                    "想直接用手拖也行 —— 关掉面板拖它，拖完自动记住。",
                11.5f, Ui.TEXT_DIM
            )
        )

        val presetRow = linear(vertical = false)
        presetRow.layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
        ).also { it.topMargin = dp(11) }
        // 比例刻意不推到头（不用 0.98 / 1.0）：屏幕左右边缘约 20dp 是系统"返回手势"的
        // 起手区，从那里起划会被系统抢走 —— 拖动会变成返回。留出来的余量见 PetConfig。
        for ((label, fr) in listOf(
            "右下" to (0.76f to 0.86f),
            "左下" to (0.24f to 0.86f),
            "中下" to (0.50f to 0.90f),
            "右上" to (0.76f to 0.26f),
            "左上" to (0.24f to 0.26f)
        )) {
            // 每个按钮一份 LayoutParams：共用一个实例在带权重的 LinearLayout 里是雷
            presetRow.addView(
                smallButton(label) { applyPosFrac(fr.first, fr.second) },
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                    .also { it.rightMargin = dp(4) }
            )
        }
        posCard.addView(presetRow)

        posXValue = textView("", 13f, Ui.ACCENT)
        posYValue = textView("", 13f, Ui.ACCENT)

        val s0 = screen()
        posXBar = addPosSlider(
            posCard, "水平（左右）", posXValue!!, POS_X_MIN, POS_X_SPAN, posPctX(s0) - POS_X_MIN
        ) { applyPos() }
        posYBar = addPosSlider(
            posCard, "竖直（脚底高度）", posYValue!!, POS_Y_MIN, POS_Y_SPAN, posPctY(s0) - POS_Y_MIN
        ) { applyPos() }

        col.addView(posCard)
        marginBottom(posCard, 18)

        // ---------- 快捷动作
        shortcutLabel = sectionLabel("快捷动作")
        col.addView(shortcutLabel)
        shortcutBox = linear(vertical = false, bg = Ui.CARD, paddingDp = 12)
        shortcutBox.addView(
            smallButton("说句话") { sendDo("speak") },
            weight()
        )
        shortcutBox.addView(
            smallButton("敲键盘") { sendDo("work") },
            weight()
        )
        shortcutBox.addView(
            smallButton("干饭") { sendDo("eat") },
            weight()
        )
        shortcutBox.addView(
            smallButton("变条鱼") { sendDo("whale") },
            weight()
        )
        col.addView(shortcutBox)
        marginBottom(shortcutBox, 18)

        // ---------- 外观
        col.addView(sectionLabel("外观"))

        val sizeCard = linear(bg = Ui.CARD, paddingDp = 14)
        val sizeHead = linear(vertical = false)
        val sizeTitle = textView("大小", 15f, Ui.TEXT)
        sizeHead.addView(sizeTitle, weight())
        sizeValue = textView("", 13f, Ui.ACCENT)
        sizeHead.addView(sizeValue!!)
        sizeCard.addView(sizeHead)
        val sizeBar = SeekBar(this).apply {
            max = PetConfig.MAX_DP - PetConfig.MIN_DP
            progress = cfg.sizeDp - PetConfig.MIN_DP
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                    cfg.sizeDp = PetConfig.MIN_DP + p
                    sizeValue?.text = "${cfg.sizeDp} dp"
                    if (fromUser) broadcastConfigure()
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        sizeCard.addView(sizeBar)
        sizeRow = sizeCard
        col.addView(sizeCard)
        marginBottom(sizeCard, 10)

        val opCard = linear(bg = Ui.CARD, paddingDp = 14)
        val opHead = linear(vertical = false)
        opHead.addView(textView("透明度", 15f, Ui.TEXT), weight())
        opValue = textView("", 13f, Ui.ACCENT)
        opHead.addView(opValue!!)
        opCard.addView(opHead)
        val opBar = SeekBar(this).apply {
            max = 100 - Math.round(PetConfig.MIN_OP * 100)
            progress = Math.round(cfg.opacity * 100) - Math.round(PetConfig.MIN_OP * 100)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                    cfg.opacity = (Math.round(PetConfig.MIN_OP * 100) + p) / 100f
                    opValue?.text = "${Math.round(cfg.opacity * 100)}%"
                    if (fromUser) broadcastConfigure()
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        opCard.addView(opBar)
        opRow = opCard
        col.addView(opCard)
        marginBottom(opCard, 18)

        // ---------- 行为
        col.addView(sectionLabel("行为"))
        val behavior = linear(bg = Ui.CARD, paddingDp = 14)
        behavior.addView(switchRow("台词气泡", "在头顶弹一句话", cfg.bubble) {
            cfg.bubble = it; broadcastConfigure()
        })
        behavior.addView(hRule())
        behavior.addView(switchRow("交互音效", "摸它、拖它、切换动作时的短音", cfg.sfx) {
            cfg.sfx = it; broadcastConfigure()
        })
        behavior.addView(hRule())
        behavior.addView(switchRow("待机小动作", "没人理的时候自己演一段", cfg.idleAction) {
            cfg.idleAction = it; broadcastConfigure()
        })
        behavior.addView(hRule())
        behavior.addView(switchRow("眨眼", "待机时随机眨眼", cfg.blink) {
            cfg.blink = it; broadcastConfigure()
        })
        behavior.addView(hRule())
        behavior.addView(
            switchRow(
                "锁定位置",
                "拖不动它 —— 位置只能从这个面板改，手滑碰不到。单击、双击、长按照常响应。",
                cfg.pinPos
            ) { cfg.pinPos = it; broadcastConfigure() }
        )
        behavior.addView(hRule())
        behavior.addView(
            switchRow(
                "触摸穿透（纯观赏）",
                "宠物完全不接收触摸：点它、长按它都没反应，手指直接落到下面的 app。" +
                    "它盖住的那块区域也不再挡任何操作，代价是只剩观赏。",
                cfg.passthrough
            ) { cfg.passthrough = it; broadcastConfigure() }
        )
        col.addView(behavior)
        marginBottom(behavior, 18)

        // ---------- 关于
        col.addView(sectionLabel("关于"))
        val about = linear(bg = Ui.CARD, paddingDp = 15)
        about.addView(textView("${App.NAME} · 手机版 v${App.VERSION}", 15f, Ui.TEXT, bold = true))
        contentInfo = textView("", 12.5f, Ui.TEXT_DIM)
        contentInfo.setPadding(0, dp(6), 0, 0)
        about.addView(contentInfo)
        val tip = textView(
            "单击宠物逗它、双击跳一下、长按打开本面板、关掉面板后拖它换位置。" +
                "面板开着的时候它暂时不接收触摸（不然会挡住下面的控件），改位置用上面的滑块。" +
                "屏幕熄灭时它会睡觉，亮起来自己醒来。",
            12f, Ui.TEXT_DIM
        )
        tip.setPadding(0, dp(10), 0, 0)
        about.addView(tip)
        col.addView(about)

        setContentView(scroll)
        refresh()
    }

    private fun sectionLabel(text: String): TextView =
        textView(text, 13f, Ui.TEXT_DIM, bold = true).apply {
            val lp = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT
            )
            lp.bottomMargin = dp(9)
            layoutParams = lp
        }

    private fun weight(): LinearLayout.LayoutParams = LinearLayout.LayoutParams(
        0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f
    ).also { it.rightMargin = dp(4) }

    private fun smallButton(text: String, onClick: () -> Unit): Button = Button(this).apply {
        this.text = text
        textSize = 13.5f
        setTextColor(Ui.TEXT)
        isAllCaps = false
        background = roundBg(Ui.CARD_HI, 10f)
        setPadding(0, dp(11), 0, dp(11))
        setOnClickListener { onClick() }
    }

    private fun switchRow(
        title: String,
        sub: String,
        init: Boolean,
        onChange: (Boolean) -> Unit
    ): LinearLayout {
        val row = linear(vertical = false, paddingDp = 0)
        row.setPadding(0, dp(11), 0, dp(11))
        val textBox = linear()
        textBox.layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        textBox.addView(textView(title, 14.5f, Ui.TEXT))
        if (sub.isNotEmpty()) {
            val s = textView(sub, 11.5f, Ui.TEXT_DIM)
            s.setPadding(0, dp(4), dp(10), 0)
            textBox.addView(s)
        }
        row.addView(textBox)
        val sw = Switch(this).apply {
            isChecked = init
            setOnCheckedChangeListener { _, v -> onChange(v) }
        }
        row.addView(sw)
        return row
    }

    // ------------------------------------------------------------ 位置

    /**
     * 一根位置滑块。刻度是**屏幕宽/高的百分比**，映射到锚点（宠物脚底中心）的实际像素。
     *
     * 起点不是 0%：宠物贴到屏幕边缘时 `placeByAnchor` 会把它钳回来，滑块再往外推
     * 宠物也不动 —— 那看着像"滑块坏了"。索性让滑块的可达范围就是真实可达范围。
     */
    private fun addPosSlider(
        card: LinearLayout,
        label: String,
        value: TextView,
        lo: Int,
        span: Int,
        start: Int,
        onChange: () -> Unit
    ): SeekBar {
        val head = linear(vertical = false)
        head.addView(textView(label, 14.5f, Ui.TEXT), weight())
        head.addView(value)
        head.layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
        ).also { it.topMargin = dp(12) }
        card.addView(head)

        val bar = SeekBar(this).apply {
            max = span
            progress = start.coerceIn(0, span)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                    value.text = "${lo + p}%"
                    if (fromUser) onChange()
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        // 上面那行 progress 是在挂监听之前赋的，不会回调 —— 标签自己先写一次
        value.text = "${lo + bar.progress}%"
        card.addView(bar)
        return bar
    }

    /** 滑块松手：把两个百分比换算成锚点像素写进配置，再让服务去摆窗口。 */
    private fun applyPos() {
        val s = screen()
        val xf = (POS_X_MIN + (posXBar?.progress ?: 0)) / 100f
        val yf = (POS_Y_MIN + (posYBar?.progress ?: 0)) / 100f
        cfg.savePos(s[0] * xf, s[1] * yf)
        broadcastConfigure()
    }

    /** 预设角落。比例值见 [PetConfig.DEFAULT_X_FRAC] 的注释（避系统手势热区）。 */
    private fun applyPosFrac(fx: Float, fy: Float) {
        val s = screen()
        cfg.savePos(s[0] * fx, s[1] * fy)
        syncPosControls()
        broadcastConfigure()
    }

    /** 把配置里的位置回灌到两根滑块上（点完预设按钮要跟着动）。 */
    private fun syncPosControls() {
        val s = screen()
        posXBar?.progress = (posPctX(s) - POS_X_MIN).coerceIn(0, POS_X_SPAN)
        posYBar?.progress = (posPctY(s) - POS_Y_MIN).coerceIn(0, POS_Y_SPAN)
        posXValue?.text = "${POS_X_MIN + (posXBar?.progress ?: 0)}%"
        posYValue?.text = "${POS_Y_MIN + (posYBar?.progress ?: 0)}%"
    }

    private fun posPctX(s: IntArray): Int =
        Math.round((if (cfg.hasPos()) cfg.posX else s[0] * PetConfig.DEFAULT_X_FRAC) / s[0] * 100f)

    private fun posPctY(s: IntArray): Int =
        Math.round((if (cfg.hasPos()) cfg.posY else s[1] * PetConfig.DEFAULT_Y_FRAC) / s[1] * 100f)

    /**
     * 真实屏幕尺寸（物理像素）。
     *
     * 不能用 `resources.displayMetrics`：那是**应用窗口**的尺寸，跟真实屏幕差着一个
     * 状态栏/导航栏，换算出来的百分比会和悬浮服务（它走 DisplayManager）差 3%~5%，
     * 点同一个预设在大屏机上落点就不一样。
     */
    private fun screen(): IntArray {
        val dm = getSystemService(DisplayManager::class.java)
        val d: Display? = dm?.getDisplay(Display.DEFAULT_DISPLAY)
        val m = DisplayMetrics()
        @Suppress("DEPRECATION")
        d?.getRealMetrics(m)
        if (m.widthPixels > 0) return intArrayOf(m.widthPixels, m.heightPixels)
        val f = resources.displayMetrics
        return intArrayOf(f.widthPixels, f.heightPixels)
    }

    // ------------------------------------------------------------ 状态刷新

    private fun refresh() {
        val canOverlay = Settings.canDrawOverlays(this)
        val on = cfg.enabled

        statusDot.background = roundBg(if (on) Ui.ACCENT else Ui.TEXT_DIM, 5f)
        statusTitle.text = if (on) "桌宠运行中" else "桌宠已停止"
        statusSub.text = if (!canOverlay) "尚未授予悬浮窗权限"
        else if (on) "正在屏幕上陪着你"
        else "点下面的按钮把它放到屏幕上"
        toggleBtn.text = if (on) "停止桌宠" else "开启桌宠"
        toggleBtn.background = roundBg(if (on) Ui.DANGER else Ui.ACCENT, 12f)

        permBox.visibility = if (canOverlay) View.GONE else View.VISIBLE

        val active = if (on && canOverlay) View.VISIBLE else View.GONE
        // 快捷动作是"命令服务做事"，服务没跑就没有接收方，藏起来
        shortcutLabel.visibility = active
        shortcutBox.visibility = active
        // 外观与行为**始终可调**：服务没跑的时候改的是"下次启动生效"的配置，
        // 没有理由藏起来。早先跟着一起隐藏的后果是标题孤零零留在那里，看着像坏了。
        sizeRow.visibility = View.VISIBLE
        opRow.visibility = View.VISIBLE

        sizeValue?.text = "${cfg.sizeDp} dp"
        opValue?.text = "${Math.round(cfg.opacity * 100)}%"
        syncPosControls()

        contentInfo.text = contentSummary()
    }

    private fun contentSummary(): String = try {
        val text = assets.open("content/actions.json").use { it.readBytes().toString(Charsets.UTF_8) }
        val root = MiniJson.parse(text) as? Map<*, *>
        val ver = (root?.get("content_version") as? Double)?.toInt() ?: 0
        val assets = (root?.get("assets") as? Map<*, *>)?.size ?: 0
        val states = (root?.get("states") as? Map<*, *>)?.size ?: 0
        "内容包 v$ver · $assets 帧素材 · $states 个状态"
    } catch (_: Throwable) {
        "内容包读取失败"
    }

    // ------------------------------------------------------------ 动作

    private fun startPet() {
        if (!Settings.canDrawOverlays(this)) {
            DLog.w("尚未授予悬浮窗权限，转到系统设置")
            openOverlaySettings()
            return
        }
        requestNotifPermission()
        cfg.enabled = true
        DLog.i("用户开启桌宠")
        ensureService()
        // 服务起来是异步的，稍等一下再刷新状态，免得按钮显示"已停止"骗人
        toggleBtn.postDelayed({ refresh() }, 400)
    }

    /** 幂等：服务已经在跑时再发一次只是让它重读配置。 */
    private fun ensureService() {
        try {
            val i = Intent(this, OverlayService::class.java)
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
        } catch (e: Throwable) {
            DLog.e("启动桌宠服务失败", e)
        }
    }

    private fun stopPet() {
        cfg.enabled = false
        DLog.i("用户停止桌宠")
        stopService(Intent(this, OverlayService::class.java))
        refresh()
    }

    private fun openOverlaySettings() {
        try {
            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName")
                )
            )
        } catch (_: Throwable) {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION))
        }
    }

    private fun requestNotifPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                != android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
            }
        }
    }

    private fun broadcastConfigure() {
        sendBroadcast(
            Intent(OverlayService.ACTION_CONFIGURE).setPackage(packageName)
        )
    }

    private fun sendDo(kind: String) {
        sendBroadcast(
            Intent(OverlayService.ACTION_DO)
                .setPackage(packageName)
                .putExtra(OverlayService.EXTRA_KIND, kind)
        )
    }

    companion object {
        /**
         * 位置滑块的可达范围（屏幕百分比）。
         *
         * 上下限都不是 0/100：宠物脚底贴到屏幕边缘时 `placeByAnchor` 会把它钳回来，
         * 滑块再往外推宠物也不动 —— 看着像"滑块坏了"。让滑块的范围就是真实可达范围。
         */
        private const val POS_X_MIN = 5
        private const val POS_X_SPAN = 90        // 5% .. 95%
        private const val POS_Y_MIN = 15
        private const val POS_Y_SPAN = 85        // 15% .. 100%
    }
}
