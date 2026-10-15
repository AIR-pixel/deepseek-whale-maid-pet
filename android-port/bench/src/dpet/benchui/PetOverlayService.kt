package dpet.benchui

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.PixelFormat
import android.graphics.Rect
import android.hardware.display.DisplayManager
import android.os.Build
import android.os.Debug
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.util.DisplayMetrics
import android.util.Log
import android.view.Choreographer
import android.view.Display
import android.view.Gravity
import android.view.WindowManager
import java.io.File
import java.util.Locale

private const val TAG = "PETOVL"
private const val CHAN_ID = "petovl"

/**
 * 悬浮窗基准。
 *
 * 这是"桌面常驻宠物"的真实形态：`TYPE_APPLICATION_OVERLAY` 窗口 + 前台服务宿主。
 * 与全屏 POC 的区别只在于**窗口大小与层级**，渲染管线完全复用同一个 [PetView]。
 *
 * 三个要验证的问题：
 *   1. HyperOS 到底让不让 addView（受控权限 + 国产 ROM 的"后台弹出界面"）
 *   2. 悬浮窗形态下的 CPU 占用（传说比全屏省 —— 要证伪或证实）
 *   3. 帧驱动改成 vsync 整数分频后，节拍是否真的均匀了
 */

/** driver = 每 N 个 vsync 画一次。60Hz 下：1→60fps，2→30fps，3→20fps */
private val PHASES = listOf(
    Phase("ovl60", 1, 8.0),
    Phase("ovl30", 2, 8.0),
    Phase("ovl20", 3, 8.0)
)

private class Phase(val name: String, val driver: Int, val secs: Double)

class PetOverlayService : Service() {

    private var pack: Pack? = null
    private var view: PetView? = null
    private var wm: WindowManager? = null
    private val handler = Handler(Looper.getMainLooper())
    private val results = ArrayList<String>()

    private var petH = 280
    private var phaseIdx = -1
    private var cur: Phase? = null
    private var stats = PerfStats()
    private var phaseStartNs = 0L
    private var phaseStartCpu = 0L
    private var lastDrawNs = 0L
    private var decimCount = 0L
    private var t = 0.0
    private var running = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        petH = intent?.getIntExtra("h", 280) ?: 280
        startForegroundCompat()
        handler.post { safeBoot() }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        running = false
        Choreographer.getInstance().removeFrameCallback(vsyncCb)
        view?.let { v ->
            try {
                wm?.removeView(v)
            } catch (_: Throwable) {
            }
        }
        super.onDestroy()
    }

    // ------------------------------------------------------------ 前台服务

    private fun startForegroundCompat() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHAN_ID, "桌宠悬浮窗", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHAN_ID)
        else @Suppress("DEPRECATION") Notification.Builder(this)
        val notif = b
            .setContentTitle("桌宠悬浮窗基准")
            .setContentText("正在测量")
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setOngoing(true)
            .build()

        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notif)
        }
    }

    // ------------------------------------------------------------ 建窗

    /**
     * boot 外面必须包一层。
     *
     * 上一次踩的坑：boot 里抛异常 → 进程被杀 → **没有任何结果文件**，
     * 只能靠翻 crash buffer 才找得到原因。任何异常都要先落盘再走。
     */
    private fun safeBoot() {
        try {
            boot()
        } catch (e: Throwable) {
            note("ERROR boot 异常: $e")
            note(e.stackTraceToString().take(2000))
            writeOut()
        }
    }

    private fun boot() {
        val canDraw = Settings.canDrawOverlays(this)

        val t0 = System.nanoTime()
        val p = try {
            Pack(this)
        } catch (e: Throwable) {
            note("ERROR pack 构建失败: $e")
            return
        }
        pack = p
        val loadMs = (System.nanoTime() - t0) / 1e6

        val dm = resources.displayMetrics
        val density = dm.density
        val hPx = (petH * density).toInt()

        val t1 = System.nanoTime()
        p.rescale(hPx)
        val prescaleMs = (System.nanoTime() - t1) / 1e6

        // 窗口尺寸 = 最大帧 + 动效余量（与桌面端 _rescale 同一口径）
        var maxW = 1
        var maxH = 1
        for (sz in p.lsize.values) {
            if (sz[0] > maxW) maxW = sz[0]
            if (sz[1] > maxH) maxH = sz[1]
        }
        val pad = p.pad
        val winW = maxW + pad * 2
        val winH = maxH + pad * 2

        val bounds = screenBounds()
        val margin = (16 * density).toInt()
        val bottom = (72 * density).toInt()
        val x = bounds.width() - winW - margin
        val y = bounds.height() - winH - bottom

        wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager

        val v = PetView(this, p)
        v.petCount = 1
        v.drawBg = false          // 悬浮窗：窗外留透明，不要铺底色
        v.margin = 0f             // 窗口已按 pad 留好余量
        view = v

        val lp = WindowManager.LayoutParams(
            winW, winH,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            this.x = x
            this.y = y
        }

        val t2 = System.nanoTime()
        var added = false
        var err = ""
        try {
            wm!!.addView(v, lp)
            added = true
        } catch (e: Throwable) {
            err = e.toString()
        }
        val addMs = (System.nanoTime() - t2) / 1e6

        note(
            String.format(
                Locale.US,
                "OVERLAY canDrawOverlays=%s added=%s addMs=%.1f err=%s win=%dx%d pad=%d pos=(%d,%d) " +
                    "screen=%dx%d density=%.2f hPx=%d refresh=%.2fHz loadMs=%.1f prescaleMs=%.1f " +
                    "sdk=%d fgsTypeOk=%s",
                canDraw, added, addMs, err, winW, winH, pad, x, y,
                bounds.width(), bounds.height(), density, hPx, refreshRate(), loadMs, prescaleMs,
                Build.VERSION.SDK_INT, Build.VERSION.SDK_INT >= 34
            )
        )

        if (!added) {
            writeOut()
            return
        }

        v.onFrameDone = { checkPhase() }
        handler.postDelayed({ beginPhase(0) }, 800)
    }

    // 注意：**不能用 `Service.display` / `Context.getDisplay()`**。
    // Service 的 Context 不是「可视 Context」，Android 16 上会直接抛
    //   UnsupportedOperationException: Tried to obtain display from a Context not associated with one.
    // （Activity 里没事，因为 Activity 是可视的 —— 这个差异很容易漏掉。）
    // 正确做法是走 DisplayManager 拿默认显示。
    private fun defaultDisplay(): Display? =
        getSystemService(DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY)

    private fun screenBounds(): Rect {
        val m = DisplayMetrics()
        @Suppress("DEPRECATION")
        defaultDisplay()?.getRealMetrics(m)
        if (m.widthPixels == 0) {
            val dm = resources.displayMetrics
            return Rect(0, 0, dm.widthPixels, dm.heightPixels)
        }
        return Rect(0, 0, m.widthPixels, m.heightPixels)
    }

    private fun refreshRate(): Double = defaultDisplay()?.refreshRate?.toDouble() ?: 0.0

    // ------------------------------------------------------------ 帧驱动

    private val vsyncCb: Choreographer.FrameCallback = object : Choreographer.FrameCallback {
        override fun doFrame(frameTimeNanos: Long) {
            val s = cur ?: return
            if (!running) return
            Choreographer.getInstance().postFrameCallback(this)

            decimCount++
            if (s.driver > 1 && decimCount % s.driver != 0L) return

            val now = System.nanoTime()
            if (lastDrawNs != 0L) t += (now - lastDrawNs) / 1e9
            lastDrawNs = now
            view?.let {
                it.t = t
                it.invalidate()
            }
        }
    }

    // ------------------------------------------------------------ 阶段机

    private fun beginPhase(i: Int) {
        phaseIdx = i
        if (i >= PHASES.size) {
            runEngineBench()
            writeOut()
            // 留着窗口不撤 —— 便于截图验证它真的浮在别的应用之上
            view?.hud = "DONE"
            view?.invalidate()
            return
        }
        val s = PHASES[i]
        cur = s
        t = 0.0
        lastDrawNs = 0L
        decimCount = 0L
        stats = PerfStats()
        view?.let {
            it.t = 0.0
            it.liveStats = stats
            it.hud = "overlay ${s.name}"
        }
        phaseStartNs = System.nanoTime()
        phaseStartCpu = Debug.threadCpuTimeNanos()
        running = true
        Choreographer.getInstance().postFrameCallback(vsyncCb)
    }

    private fun checkPhase() {
        val s = cur ?: return
        if (!running) return
        if ((System.nanoTime() - phaseStartNs) / 1e9 >= s.secs) endPhase()
    }

    private fun endPhase() {
        val s = cur ?: return
        running = false
        Choreographer.getInstance().removeFrameCallback(vsyncCb)

        val wall = (System.nanoTime() - phaseStartNs) / 1e9
        val cpu = (Debug.threadCpuTimeNanos() - phaseStartCpu) / 1e9
        val st = stats
        val f = st.frames.coerceAtLeast(1)

        note(
            String.format(
                Locale.US,
                "RESULT phase=%-7s driver=%d pets=1 wall=%.2fs frames=%d fps=%.2f " +
                    "p50=%.2fms p95=%.2fms p99=%.2fms draw=%.3fms/frame " +
                    "cpu=%.2f%% cpuPerFrame=%.3fms",
                s.name, s.driver, wall, st.frames, st.frames / wall,
                st.percentile(0.50) / 1e6, st.percentile(0.95) / 1e6, st.percentile(0.99) / 1e6,
                st.drawNanos / 1e6 / f, cpu / wall * 100.0, cpu / f * 1e6 / 1000.0
            )
        )
        beginPhase(phaseIdx + 1)
    }

    /** 成批测量。为什么不能逐次计时见 [EngineBench] 的注释（抢占会把结果虚高几十倍）。 */
    private fun runEngineBench() {
        val p = pack ?: return
        for (line in EngineBench.run(p.motion)) note(line)
    }

    // ------------------------------------------------------------ 输出

    private fun note(line: String) {
        Log.i(TAG, line)
        results.add(line)
    }

    private fun writeOut() {
        Log.i(TAG, "SUMMARY_BEGIN")
        for (r in results) Log.i(TAG, r)
        Log.i(TAG, "SUMMARY_END")
        try {
            val dir = getExternalFilesDir(null) ?: File(filesDir, "out").also { it.mkdirs() }
            File(dir, "overlay.txt").writeText(results.joinToString("\n") + "\n")
        } catch (e: Throwable) {
            Log.i(TAG, "WRITE_FAIL $e")
        }
    }
}

/** 极简启动器：起完服务就退，界面完全交给悬浮窗 */
class OverlayLauncherActivity : android.app.Activity() {
    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        val i = Intent(this, PetOverlayService::class.java)
        i.putExtra("h", intent.getIntExtra("h", 280))
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
        finish()
    }
}
