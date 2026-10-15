package dpet.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
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
                "锁定位置（触摸穿透）",
                "开启后手指划过宠物会直接点到下面的 app，代价是不能再拖动它。" +
                    "这是悬浮窗的取舍：系统不会把落在透明区域的触摸转发给下层窗口。",
                cfg.locked
            ) { cfg.locked = it; broadcastConfigure() }
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
            "单击宠物逗它、双击跳一下、长按打开本面板、拖动换位置。" +
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

    private fun sendPanel(open: Boolean) {
        sendBroadcast(
            Intent(OverlayService.ACTION_PANEL)
                .setPackage(packageName)
                .putExtra(OverlayService.EXTRA_OPEN, open)
        )
    }

    private fun sendDo(kind: String) {
        sendBroadcast(
            Intent(OverlayService.ACTION_DO)
                .setPackage(packageName)
                .putExtra(OverlayService.EXTRA_KIND, kind)
        )
    }
}
