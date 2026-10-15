package dpet.app

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.graphics.PixelFormat
import android.graphics.Rect
import android.hardware.display.DisplayManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.view.Choreographer
import android.view.Display
import android.view.Gravity
import android.view.WindowManager

/**
 * 桌宠悬浮窗的宿主。
 *
 * 结构：**一个前台服务带两个窗口**。
 *
 * * `PetView`（可触摸）—— 尺寸严格等于「当前帧 + 2×动效余量」。帧在窗口里的位置
 *   永远是 `(pad, pad)`，所以只要窗口跟着帧尺寸走 + 脚底锚点固定，宠物在屏幕上
 *   的位置就恒定不漂。刻意**不用**"所有帧的最大包围盒"当窗口：那会把窗口撑到
 *   whale 那种 188dp 宽，多出来的透明区域会白吃掉一大块触摸。
 * * `BubbleView`（`FLAG_NOT_TOUCHABLE`）—— 气泡比宠物宽得多，塞进宠物窗口
 *   就等于把它撑成气泡的宽度。拆开之后气泡完全不参与触摸分发。
 *
 * 这是 Android 悬浮窗的硬边界：**没有"把落在透明像素上的触摸转发给下层窗口"
 * 这种机制**（桌面版靠 `QRegion` mask 做到的事，这里做不到）。能做的只有
 * 让窗口尽量小，以及提供一个"锁定位置 = 整窗触摸穿透"的开关。
 */
class OverlayService : Service() {

    companion object {
        private const val CHAN_ID = "pet_overlay"
        private const val NOTIF_ID = 1

        const val ACTION_CONFIGURE = "dpet.app.CONFIGURE"
        const val ACTION_DO = "dpet.app.DO"
        const val EXTRA_KIND = "kind"
        // 「面板是否在前台」不走广播，走同进程的 PanelState —— 早期那对
        // ACTION_PANEL / EXTRA_OPEN 常量已经删掉，别再把它捡回来。

        /** 目标帧率。POC 实测：vsync 整数分频比墙钟定时器稳，30fps 足够。 */
        private const val TARGET_FPS = 30.0
        private const val FRAME_NS = (1_000_000_000.0 / TARGET_FPS).toLong()
        private const val MAX_DT = 0.25

        /** 气泡最大宽度（dp），与桌面版 Bubble.MAX_W=260 同口径但按手机缩一档 */
        private const val BUBBLE_MAX_W_DP = 240

        /** 气泡停留时长（毫秒），与桌面版 `show_text` 默认 3600 一致 */
        private const val BUBBLE_MS = 3600L
    }

    private val density: Float get() = resources.displayMetrics.density

    private fun dp(v: Int): Int = Math.round(v * density)

    private fun dpF(v: Float): Float = v * density

    private lateinit var cfg: PetConfig
    private var pack: Pack? = null
    private var state: PetState? = null
    private var sfx: Sfx? = null

    private var wm: WindowManager? = null
    private var notifManager: NotificationManager? = null
    private var petView: PetView? = null
    private var petLp: WindowManager.LayoutParams? = null
    private var bubbleView: BubbleView? = null
    private var bubbleLp: WindowManager.LayoutParams? = null

    /** 宠物「脚底中心」在屏幕上的坐标 —— 窗口尺寸怎么变都不动这个点 */
    private var anchorX = 0f
    private var anchorY = 0f

    private var lastSyncedFrame = ""
    private var lastUserNs = 0L
    private var lastDrawNs = 0L
    private var running = false
    private var bubbleHideToken = 0

    /** 手指正按在宠物上（`ACTION_DOWN` 到 `ACTION_UP/CANCEL` 之间）。 */
    private var pressed = false

    /** 手势进行中被推迟掉的换尺寸请求，抬手后补做。见 [pushFrame]。 */
    private var resizePending = false

    /**
     * 控制面板在前台。
     *
     * 打开面板时把宠物窗口临时设成 `FLAG_NOT_TOUCHABLE`：否则宠物飘在设置项上面，
     * 手指落在它覆盖的那一块会被 overlay 吃掉 —— 实测拖"大小"滑块时，
     * 滑块纹丝不动，宠物反而被拖走了。面板关掉就恢复，用户感知不到这层切换。
     */
    private var panelOpen = false

    private val handler = Handler(Looper.getMainLooper())

    /**
     * 锁屏是否还在。
     *
     * `ACTION_USER_PRESENT` 是"keyguard 被解开"时才发的广播，各家 ROM 行为不一 ——
     * 本机 HyperOS 实测：设了密码锁屏时我没法用 adb 解开，而把锁屏整个关掉之后
     * 这个广播**根本不会发**（没有 keyguard 可解）。所以帧循环里另外用它兜一次底，
     * 让"亮屏了、锁屏也开了"这件事无论走哪条路都能兑现问候。
     */
    private val keyguard by lazy {
        getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
    }

    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context?, intent: Intent?) {
            when (intent?.action) {
                Intent.ACTION_SCREEN_OFF -> {
                    DLog.i("屏幕灭 -> sleep")
                    running = false
                    state?.onScreenOff()
                    lastUserNs = System.nanoTime()
                    pushFrame(force = true)
                }
                Intent.ACTION_SCREEN_ON -> {
                    lastUserNs = System.nanoTime()
                    state?.onScreenOn()
                    DLog.i("亮屏 · keyguardLocked=${keyguard.isKeyguardLocked}")
                    if (!running) startDriver()
                }
                Intent.ACTION_USER_PRESENT -> {
                    DLog.i("解锁 -> 醒来")
                    lastUserNs = System.nanoTime()
                    state?.onUserPresent()
                    if (!running) startDriver()
                }
                ACTION_CONFIGURE -> applyConfig()
                ACTION_DO -> doShortcut(intent.getStringExtra(EXTRA_KIND) ?: "")
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        DLog.init(this)
        cfg = PetConfig(this)
        wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager

        val f = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_USER_PRESENT)
            addAction(ACTION_CONFIGURE)
            addAction(ACTION_DO)
        }
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(screenReceiver, f, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(screenReceiver, f)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat()
        if (petView == null) handler.post { safeBoot() } else applyConfig()
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        Choreographer.getInstance().removeFrameCallback(frameCb)
        runCatching { unregisterReceiver(screenReceiver) }
        runCatching {
            petView?.let { wm?.removeView(it) }
            bubbleView?.let { wm?.removeView(it) }
        }
        PanelState.clear()
        petView = null
        bubbleView = null
        sfx?.release()
        sfx = null
        pack?.release()
        pack = null
        super.onDestroy()
    }

    // ------------------------------------------------------------ 启动

    private fun startForegroundCompat() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHAN_ID, "桌宠", NotificationManager.IMPORTANCE_MIN)
            )
        }
        notifManager = nm
        val notif = buildNotification()

        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIF_ID, notif)
        }
    }

    /**
     * 通知栏文案跟着配置走，[updateNotification] 会在配置变化后刷一次。
     *
     * 为什么值得为这几行单开一个函数：宠物一旦"不吃触摸"（`passthrough` 开着，或控制面板
     * 在前台），用户点它就是毫无反应，而屏幕上没有任何东西解释这件事 —— 只能得到一个
     * "这软件坏了"的结论。通知栏是唯一常驻的入口，把"为什么没反应 + 去哪儿改"摆在上面，
     * 比在别处写多少行说明都管用。
     */
    private fun buildNotification(): Notification {
        val pi = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHAN_ID)
        else @Suppress("DEPRECATION") Notification.Builder(this)

        val title: String
        val text: String
        if (cfg.passthrough) {
            title = "鲸鱼娘 · 触摸穿透中"
            text = "它现在不接收触摸。要恢复：点这里打开面板，关掉「触摸穿透」"
        } else if (cfg.pinPos) {
            title = "鲸鱼娘 · 位置已锁定"
            text = "点它照常互动；换位置去控制面板，或先关掉「锁定位置」"
        } else {
            title = "鲸鱼娘在屏幕上"
            text = "点按互动 · 双击跳一下 · 长按打开控制面板 · 拖动换位置"
        }

        return b
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentIntent(pi)
            .setOngoing(true)
            .setShowWhen(false)
            .build()
    }

    /** 配置变了就刷新通知栏文案。失败无所谓（通知权限没给就是空操作）。 */
    private fun updateNotification() {
        runCatching { notifManager?.notify(NOTIF_ID, buildNotification()) }
    }

    private fun safeBoot() {
        try {
            boot()
        } catch (e: Throwable) {
            DLog.e("boot 失败", e)
            stopSelf()
        }
    }

    private fun boot() {
        val t0 = System.nanoTime()
        val p = Pack.load(this)
        p.rescale(this.dp(cfg.sizeDp))
        pack = p
        DLog.i("内容包就绪 v${p.contentVersion} · ${p.frameNames.size} 帧 · " +
                "${p.states.size} 状态 · pad=${p.pad}px · " +
                "耗时 ${(System.nanoTime() - t0) / 1_000_000}ms")

        sfx = Sfx().apply {
            enabled = cfg.sfx
            volume = cfg.sfxVolume
            load(this@OverlayService)
        }

        val st = PetState(p)
        st.onSay = { text, cue -> say(text, cue) }
        state = st

        val sb = screenBounds()
        if (cfg.hasPos()) {
            anchorX = cfg.posX
            anchorY = cfg.posY
        } else {
            // 默认落点也在"右下角"，但避开了系统手势热区，见 PetConfig 的注释
            anchorX = sb.width() * PetConfig.DEFAULT_X_FRAC
            anchorY = sb.height() * PetConfig.DEFAULT_Y_FRAC
        }

        addPetWindow()
        addBubbleWindow()

        // 面板可能已经开着（服务被回收后重建的情况），注册时就会收到当前值
        PanelState.observe { open ->
            panelOpen = open
            applyFlags()
        }

        st.start(greeting = true)
        lastUserNs = System.nanoTime()
        pushFrame(force = true)
        startDriver()
    }

    private fun addPetWindow() {
        val p = pack ?: return
        val v = PetView(this, p).apply {
            opacity = cfg.opacity
            onTap = { onPetTap() }
            onDoubleTap = { onPetDoubleTap() }
            onLongPress = { openPanel() }
            onPressChanged = { down ->
                // 触摸真的到了没有 —— 排查"点它没反应"时，这一行是第一手证据：
                // 没有"按下"就是窗口压根没收到触摸（穿透开着 / 位置在屏幕外 / 被别的窗压住），
                // 有"按下"却没"单击"就是手势被系统判成了滑动或取消。
                DLog.i(if (down) "触摸: 按下" else "触摸: 抬手")
                pressed = down
                if (!down) flushResize()
            }
            onDragStart = {
                // 锁了位置就别装作在搬 —— 手指动了却毫无位移，用户只会以为程序卡了。
                // 给一句台词，把"为什么不动"说出口。
                if (cfg.pinPos) {
                    DLog.i("拖动: 被位置锁拦下")
                    say(Lines.pick(Lines.PINNED), null)
                } else {
                    DLog.i("拖动: 开始")
                    sfx?.play("grab")
                    say(Lines.pick(Lines.DRAG), null)
                }
            }
            onDrag = { dx, dy -> onPetDrag(dx, dy) }
            onDragEnd = {
                if (!cfg.pinPos) {
                    sfx?.play("drop")
                    cfg.savePos(anchorX, anchorY)
                    DLog.i("拖动: 结束 锚点=(${anchorX.toInt()},${anchorY.toInt()})")
                }
            }
        }

        val frame = p.firstFrame()
        val sz = p.size(frame) ?: intArrayOf(1, 1)
        val lp = WindowManager.LayoutParams(
            sz[0] + p.pad * 2, sz[1] + p.pad * 2,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            baseFlags(),
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = Math.round(anchorX - width / 2f)
            y = Math.round(anchorY - height + p.pad)
        }
        // 走一遍钳制：存下来的坐标是上次那台设备/那套 DPI 的物理像素，换了环境可能整只
        // 落在屏幕外 —— 那时用户既看不到它也摸不到它，只能去清应用数据。钳制顺手把越界的
        // 锚点反推回屏幕内（placeByAnchor 会回写 anchorX/anchorY）。
        placeByAnchor(lp)

        try {
            wm!!.addView(v, lp)
        } catch (e: Throwable) {
            // 国产 ROM 的"后台弹出界面"开关没开时就会走到这里
            DLog.e("悬浮窗被拒", e)
            stopSelf()
            return
        }
        petView = v
        petLp = lp
        lastSyncedFrame = frame
        v.frameName = frame
    }

    private fun addBubbleWindow() {
        val v = BubbleView(this)
        val lp = WindowManager.LayoutParams(
            1, 1,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            baseFlags() or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
        }
        v.alpha = 0f
        try {
            wm!!.addView(v, lp)
        } catch (_: Throwable) {
            return
        }
        bubbleView = v
        bubbleLp = lp
    }

    /**
     * 两种"不吃触摸"的来源，都只是把整个窗口设成 `FLAG_NOT_TOUCHABLE`：
     *
     * * `cfg.passthrough` —— 用户自己开的"触摸穿透"，宠物变纯装饰；
     * * `panelOpen` —— 控制面板在前台。
     *
     * 面板那条**不是可选项**：overlay 永远画在 Activity 之上，面板开着时宠物一定
     * 浮在设置项上面。窗口只要还能吃触摸，它盖住的那一块控件就全废（实测：拖"大小"
     * 滑块时滑块纹丝不动，宠物反而被拖走了）。
     *
     * 但这条也带来一个必须向用户解释清楚的副作用：**面板开着的时候宠物是点不动的**，
     * 看起来浮在上面能点，其实毫无反应。所以面板里必须自带位置调节（见 MainActivity
     * 的"位置"卡片）—— 早期版本没有，用户就只能对着一个又点不动、又没处调的宠物干瞪眼。
     */
    private fun baseFlags(): Int {
        var f = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
        if (cfg.passthrough || panelOpen) f = f or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        return f
    }

    private fun applyFlags() {
        val lp = petLp ?: return
        val v = petView ?: return
        lp.flags = baseFlags()
        logFlags(lp.flags)
        runCatching { wm?.updateViewLayout(v, lp) }
    }

    /**
     * 记一行"它到底收不收触摸"。
     *
     * 屏幕上没有任何东西提示这件事，而 `dumpsys window windows` 又因 ROM 而异 ——
     * 测试机（HyperOS）的 dumpsys 里**根本列不出**我们这两个 overlay 窗。
     * 所以自己记：排查"点它没反应"时这是第一手证据，`device_check.py` 也拿它当判定依据。
     */
    private fun logFlags(flags: Int) {
        DLog.i(
            "窗口 flags=0x%08x %s".format(
                flags,
                if (flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE != 0) "不吃触摸"
                else "可触摸"
            )
        )
    }

    // ------------------------------------------------------------ 帧驱动

    private fun startDriver() {
        if (running) return          // 亮屏广播可能重复来，别把回调叠成两份
        running = true
        lastDrawNs = 0L
        Choreographer.getInstance().postFrameCallback(frameCb)
    }

    private val frameCb = object : Choreographer.FrameCallback {
        override fun doFrame(frameTimeNanos: Long) {
            if (!running) return
            Choreographer.getInstance().postFrameCallback(this)

            val now = System.nanoTime()
            val since = now - lastDrawNs
            if (lastDrawNs != 0L && since < FRAME_NS) return      // 降帧：整数个 vsync 才画
            val dt = if (lastDrawNs == 0L) PetState.TICK_DT
            else (since / 1e9).coerceAtMost(MAX_DT)
            lastDrawNs = now

            val st = state ?: return
            val idleSec = (now - lastUserNs) / 1e9
            st.tick(dt, idleSec, cfg)
            // 兜底：亮屏时被挂起的问候，在锁屏确实解开后补上（见 keyguard 字段注释）
            if (st.awaitingWakeGreeting && !keyguard.isKeyguardLocked) st.onUserPresent()
            pushFrame(force = false)
        }
    }

    private fun pushFrame(force: Boolean) {
        val p = pack ?: return
        val st = state ?: return
        val v = petView ?: return

        val want = st.frame
        // 手指按着的时候先把画面冻住。换帧就得换窗口尺寸（idle 347px 宽、whale 516px 宽），
        // 而手势进行到一半去改窗口几何，有的 ROM 会直接把这一串事件判成 CANCEL ——
        // 表现就是"点一下没反应、拖到一半断了"。抬手再一起换（见 flushResize）。
        // 尺寸没变（比如只是眨眼那两帧）就不用冻，动画照跑。
        if (pressed && !fitsWindow(want)) {
            resizePending = true
            return
        }

        v.frameName = want
        v.localT = st.localT
        if (force) v.invalidate()
        syncWindow(want)
    }

    /** 当前窗口尺寸是否正好够放这一帧（帧尺寸 + 2·pad）。 */
    private fun fitsWindow(frame: String): Boolean {
        val p = pack ?: return true
        val sz = p.size(frame) ?: return true
        val lp = petLp ?: return true
        return lp.width == sz[0] + p.pad * 2 && lp.height == sz[1] + p.pad * 2
    }

    /** 手势结束后补做被推迟的那次换尺寸。 */
    private fun flushResize() {
        if (!resizePending) return
        resizePending = false
        pushFrame(force = true)
    }

    /**
     * 让窗口尺寸跟上当前帧。
     *
     * 关键点：帧在窗口里的位置恒为 `(pad, pad)`，窗口 = 帧 + 2·pad。
     * 于是只要把窗口左上角按锚点摆好，**宠物在屏幕上的位置与帧尺寸无关** ——
     * 从小到大换帧时宠物纹丝不动，只有窗口的边缘在伸缩。
     */
    private fun syncWindow(frame: String) {
        val p = pack ?: return
        if (frame == lastSyncedFrame) return
        val sz = p.size(frame) ?: return
        val lp = petLp ?: return
        val v = petView ?: return

        lastSyncedFrame = frame
        lp.width = sz[0] + p.pad * 2
        lp.height = sz[1] + p.pad * 2
        placeByAnchor(lp)
        runCatching { wm?.updateViewLayout(v, lp) }
        positionBubble()
    }

    /**
     * 按脚底锚点摆窗口：脚底在窗口内的坐标是 `(width/2, height - pad)`。
     *
     * 钳制之后要把锚点**反推回窗口的实际位置**。不回写的后果很隐蔽：
     * 用户把宠物拖到屏幕边缘、窗口被钳住不动，但 anchorX/anchorY 还在跟着手指跑，
     * 下一次换帧按那个越界的锚点重摆窗口 —— 宠物会突然跳出去一大截。
     */
    private fun placeByAnchor(lp: WindowManager.LayoutParams) {
        val p = pack ?: return
        val sb = screenBounds()
        lp.x = Math.round(anchorX - lp.width / 2f)
            .coerceIn(-p.pad, (sb.width() - lp.width + p.pad).coerceAtLeast(-p.pad))
        lp.y = Math.round(anchorY - lp.height + p.pad)
            .coerceIn(-p.pad, (sb.height() - lp.height + p.pad).coerceAtLeast(-p.pad))

        anchorX = lp.x + lp.width / 2f
        anchorY = (lp.y + lp.height - p.pad).toFloat()
    }

    private fun onPetDrag(dx: Float, dy: Float) {
        if (cfg.pinPos) return          // 锁了位置：手势照收（好给一句"锁着呢"），窗口不搬
        val lp = petLp ?: return
        val p = pack ?: return
        val v = petView ?: return
        anchorX += dx
        anchorY += dy
        placeByAnchor(lp)
        runCatching { wm?.updateViewLayout(v, lp) }
        positionBubble()
    }

    // ------------------------------------------------------------ 互动

    private fun onPetTap() {
        lastUserNs = System.nanoTime()
        val st = state ?: return
        DLog.i("单击（当前状态 ${st.state}）")
        when (st.state) {
            "sleep" -> {
                st.setState("idle", force = true, cue = "")
                say(Lines.pick(Lines.WAKE), "wake")
            }
            "doze" -> {
                st.setState("happy", force = true, cue = "")
                say(Lines.pick(Lines.WAKE), null)
            }
            else -> {
                val roll = Math.random()
                when {
                    roll < 0.42 -> {
                        st.setState("happy", force = true, cue = "")
                        say(Lines.pick(poolFor("happy")), null)
                    }
                    roll < 0.62 -> {
                        st.setState("blindfold", force = true, cue = "")
                        say(Lines.pick(poolFor("blindfold")), null)
                    }
                    roll < 0.76 -> {
                        st.setState("whale", force = true, cue = "")
                        say(Lines.pick(poolFor("whale")), null)
                    }
                    roll < 0.86 -> {
                        st.setState("eat", force = true, cue = "")
                        say(Lines.pick(poolFor("eat")), null)
                    }
                    else -> {
                        sfx?.play("click")
                        say(Lines.pick(poolFor(st.state)), null)
                    }
                }
            }
        }
    }

    private fun onPetDoubleTap() {
        lastUserNs = System.nanoTime()
        val st = state ?: return
        sfx?.play("hop")
        st.setState("happy", force = true, cue = "")
        say(Lines.pick(Lines.DBLCLICK), null)
    }

    private fun openPanel() {
        lastUserNs = System.nanoTime()
        DLog.i("长按 -> 打开控制面板")
        try {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } catch (e: Throwable) {
            DLog.w("拉起控制面板失败", e)
        }
    }

    /** 主界面/通知栏下发的快捷动作 */
    private fun doShortcut(kind: String) {
        val st = state ?: return
        lastUserNs = System.nanoTime()
        when (kind) {
            "speak" -> say(Lines.pick(poolFor(st.state)), null)
            "work" -> {
                st.setState("work", force = true)
                say(Lines.pick(poolFor("work")), null)
            }
            "eat" -> {
                st.setState("eat", force = true)
                say(Lines.pick(poolFor("eat")), null)
            }
            "whale" -> {
                st.setState("whale", force = true)
                say(Lines.pick(poolFor("whale")), null)
            }
            "happy" -> {
                st.setState("happy", force = true)
                say(Lines.pick(poolFor("happy")), null)
            }
        }
    }

    private fun poolFor(stateName: String): List<String> {
        val custom = pack?.stateMeta(stateName)?.lines
        return if (!custom.isNullOrEmpty()) custom else Lines.byState(stateName)
    }

    // ------------------------------------------------------------ 台词气泡

    private fun say(text: String, cue: String?) {
        if (!cue.isNullOrEmpty()) sfx?.play(cue)
        if (text.isEmpty() || !cfg.bubble) return
        DLog.i("气泡: $text")
        showBubble(text)
    }

    private fun showBubble(text: String) {
        val p = pack ?: return
        val bv = bubbleView ?: return
        val lp = bubbleLp ?: return

        val size = bv.layout(text, dp(BUBBLE_MAX_W_DP))
        lp.width = size[0]
        lp.height = size[1]
        val lh = p.size(state?.frame ?: "")?.get(1) ?: 0
        val sb = screenBounds()
        val topY = anchorY - lh                     // 头顶
        lp.x = Math.round(anchorX - lp.width / 2f)
            .coerceIn(0, (sb.width() - lp.width).coerceAtLeast(0))
        lp.y = Math.round(topY - lp.height - dpF(2f))
            .coerceAtLeast(dp(4))
        bv.tailX = anchorX - lp.x                   // 被边缘推挤时尾巴仍指着宠物

        runCatching { wm?.updateViewLayout(bv, lp) }

        bubbleHideToken++
        val token = bubbleHideToken
        bv.animate().cancel()
        bv.animate().alpha(1f).setDuration(200L).start()

        handler.postDelayed({
            if (token != bubbleHideToken) return@postDelayed
            bv.animate().cancel()
            bv.animate().alpha(0f).setDuration(260L).start()
        }, BUBBLE_MS)
    }

    private fun positionBubble() {
        // 宠物被拖动时气泡跟着走；气泡不可见（alpha≈0）就不用管
        if ((bubbleView?.alpha ?: 0f) < 0.02f) return
        val lp = bubbleLp ?: return
        val lh = pack?.size(state?.frame ?: "")?.get(1) ?: 0
        val sb = screenBounds()
        lp.x = Math.round(anchorX - lp.width / 2f)
            .coerceIn(0, (sb.width() - lp.width).coerceAtLeast(0))
        lp.y = Math.round(anchorY - lh - lp.height - dpF(2f)).coerceAtLeast(dp(4))
        bubbleView?.tailX = anchorX - lp.x
        runCatching { wm?.updateViewLayout(bubbleView, bubbleLp) }
    }

    // ------------------------------------------------------------ 配置

    private fun applyConfig() {
        val p = pack ?: return
        val v = petView ?: return
        val lp = petLp ?: return

        v.opacity = cfg.opacity
        sfx?.enabled = cfg.sfx
        sfx?.volume = cfg.sfxVolume

        val want = dp(cfg.sizeDp)
        if (want != p.targetHeightPx) {
            p.rescale(want)
            lastSyncedFrame = ""            // 强制重算窗口尺寸
        }
        lp.flags = baseFlags()
        logFlags(lp.flags)                  // 面板改了「触摸穿透」时也要留痕
        DLog.i(
            "配置: ${cfg.sizeDp}dp 透明度=${Math.round(cfg.opacity * 100)}% " +
                "锁定位置=${cfg.pinPos} 触摸穿透=${cfg.passthrough}"
        )
        pushFrame(force = true)

        // 位置放在**最后**做，顺序不能换：rescale 会重算每一帧的显示尺寸，窗口尺寸跟着变，
        // 而 placeByAnchor 是拿 `lp.width/height` 反推左上角的 —— 先摆位置再 rescale，
        // 就是"按旧尺寸摆好的窗口被换成新尺寸但没重摆"，宠物当场偏出一截。
        // 面板里的位置滑块每动一下都走这条路，偏一点点都能看出来。
        if (cfg.hasPos()) {
            anchorX = cfg.posX
            anchorY = cfg.posY
            placeByAnchor(lp)               // 越界会被钳回来并回写 anchorX/anchorY
            runCatching { wm?.updateViewLayout(v, lp) }
            positionBubble()
            DLog.i("位置: 锚点=(${anchorX.toInt()},${anchorY.toInt()}) " +
                    "窗口=(${lp.x},${lp.y}) ${lp.width}x${lp.height}")
        }

        // 「触摸穿透 / 锁定位置」都改了通知栏文案，所以每轮配置都刷一次
        updateNotification()
    }

    // ------------------------------------------------------------ 杂项

    /**
     * Service 的 Context **不是可视 Context**，不能用 `getDisplay()` /
     * `resources.displayMetrics` 拿真实屏幕尺寸（Android 16 上直接抛
     * `UnsupportedOperationException`）。必须走 DisplayManager。
     */
    private fun screenBounds(): Rect {
        val dm = getSystemService(DisplayManager::class.java)
        val d: Display? = dm?.getDisplay(Display.DEFAULT_DISPLAY)
        val m = DisplayMetrics()
        @Suppress("DEPRECATION")
        d?.getRealMetrics(m)
        if (m.widthPixels > 0) return Rect(0, 0, m.widthPixels, m.heightPixels)
        val fallback = resources.displayMetrics
        return Rect(0, 0, fallback.widthPixels, fallback.heightPixels)
    }

}
