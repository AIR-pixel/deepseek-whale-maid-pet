package dpet.benchui

import android.app.Activity
import android.os.Bundle
import android.os.Debug
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Choreographer
import android.view.WindowManager
import java.io.File
import java.util.Locale

private const val TAG = "PETPERF"

/** 与桌面端 deepseek_pet.py 一致：QTimer 40ms → 25 fps，固定步长 */
private const val TICK_MS = 40L
private const val TICK_DT = 0.04

/**
 * [driver] 帧驱动方式：
 *   0 = `Handler.postDelayed(40ms)` 墙钟定时器（**复刻桌面端 QTimer 的错做法**，作对照）
 *   1 = 每个 vsync 画一次（= 60fps，上限）
 *   N>1 = 每 N 个 vsync 画一次（60/N fps，节拍精确均匀）
 */
private class Spec(
    val name: String,
    val secs: Double,
    val driver: Int,
    val pets: Int,
    val bench: Boolean
)

/**
 * 全屏基准。
 *
 * 素材与画布在 [Pack] / [PetView]（两者与悬浮窗基准共用），引擎开销在 [EngineBench]。
 * 本类只负责「排阶段 → 起停帧驱动 → 统计 → 落盘」这条流程。
 */
class PetPerfActivity : Activity() {

    private lateinit var pack: Pack
    private lateinit var view: PetView
    private val handler = Handler(Looper.getMainLooper())

    private var petH = 280
    private var basePets = 1
    private var phaseSecs = 8.0
    private var only = ""

    private val specs = ArrayList<Spec>()
    private var specIdx = -1
    private var cur: Spec? = null
    private var stats = PerfStats()
    private var phaseStartNs = 0L
    private var phaseStartCpu = 0L
    private var t = 0.0
    private var lastTickNs = 0L
    private var decimCount = 0L
    private var running = false
    private val results = ArrayList<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        petH = intent.getIntExtra("h", 280)
        basePets = intent.getIntExtra("n", 1)
        phaseSecs = intent.getIntExtra("secs", 8).toDouble()
        only = intent.getStringExtra("only") ?: ""

        val t0 = System.nanoTime()
        pack = Pack(this)
        val loadMs = (System.nanoTime() - t0) / 1e6

        val density = resources.displayMetrics.density
        val hPx = (petH * density).toInt()

        val t1 = System.nanoTime()
        pack.rescale(hPx)
        val prescaleMs = (System.nanoTime() - t1) / 1e6

        val rr = if (android.os.Build.VERSION.SDK_INT >= 30) {
            (display?.refreshRate ?: 0f).toDouble()
        } else {
            @Suppress("DEPRECATION")
            windowManager.defaultDisplay.refreshRate.toDouble()
        }

        note(
            String.format(
                Locale.US,
                "BOOT load=%.1fms prescale=%.1fms frames=%d density=%.2f hPx=%d refresh=%.2fHz unknownPrimitives=%s",
                loadMs, prescaleMs, pack.frameCount, density, hPx, rr, pack.motion.unknown.toString()
            )
        )

        view = PetView(this, pack)
        view.onFrameDone = { checkPhase() }
        setContentView(view)

        specs.add(Spec("warmup", 2.0, 1, basePets, false))
        // 对照：桌面端那套 40ms 定时器（帧间隔会在 33/50ms 之间抖，见结论 5）
        specs.add(Spec("timer25", phaseSecs, 0, basePets, false))
        specs.add(Spec("vsync60", phaseSecs, 1, basePets, false))
        // 推荐方案：60 的整数分频，节拍精确均匀
        specs.add(Spec("decim30", phaseSecs, 2, basePets, false))
        specs.add(Spec("decim20", phaseSecs, 3, basePets, false))
        specs.add(Spec("stress", phaseSecs, 1, maxOf(8, basePets), false))
        specs.add(Spec("engine", 0.0, 0, 0, true))

        if (only.isNotEmpty()) specs.removeAll { it.name != only && it.name != "warmup" }
    }

    override fun onResume() {
        super.onResume()
        if (specIdx < 0) beginPhase(0)
    }

    override fun onPause() {
        super.onPause()
        running = false
        handler.removeCallbacks(timerRun)
        Choreographer.getInstance().removeFrameCallback(vsyncCb)
    }

    // ------------------------------------------------------------ 两种驱动

    // 必须写成显式匿名对象：lambda 形式下 vsyncCb 在自己体内被引用，
    // 类型推断会陷入自递归（Kotlin 报 "type checking has run into a recursive problem"）。
    //
    // 降帧靠"每 N 个 vsync 才画一次"，而不是墙钟定时器 —— 这样帧间隔是
    // vsync 周期的精确整数倍，节拍完全均匀。t 按**距上次绘制**的真实间隔推进，
    // 所以动效速度正确，不会因为降帧而变慢。
    private val vsyncCb: Choreographer.FrameCallback = object : Choreographer.FrameCallback {
        override fun doFrame(frameTimeNanos: Long) {
            val s = cur ?: return
            if (!running || s.driver == 0) return
            Choreographer.getInstance().postFrameCallback(this)

            decimCount++
            if (s.driver > 1 && decimCount % s.driver != 0L) return

            val now = System.nanoTime()
            if (lastTickNs != 0L) t += (now - lastTickNs) / 1e9
            lastTickNs = now
            view.t = t
            view.invalidate()
        }
    }

    private val timerRun = object : Runnable {
        override fun run() {
            val s = cur ?: return
            if (!running || s.driver != 0) return
            t += TICK_DT
            view.t = t
            view.invalidate()
            handler.postDelayed(this, TICK_MS)
        }
    }

    // ------------------------------------------------------------ 阶段机

    private fun beginPhase(i: Int) {
        specIdx = i
        if (i >= specs.size) {
            finishUp()
            return
        }
        val s = specs[i]
        cur = s

        if (s.bench) {
            for (line in EngineBench.run(pack.motion)) note(line)
            beginPhase(i + 1)
            return
        }

        view.petCount = s.pets
        t = 0.0
        view.t = 0.0
        lastTickNs = 0L
        decimCount = 0L
        stats = PerfStats()
        view.liveStats = stats
        view.hud = "phase=${s.name}  pets=${s.pets}"
        phaseStartNs = System.nanoTime()
        phaseStartCpu = Debug.threadCpuTimeNanos()
        running = true

        if (s.driver == 0) handler.postDelayed(timerRun, TICK_MS)
        else Choreographer.getInstance().postFrameCallback(vsyncCb)
    }

    private fun checkPhase() {
        val s = cur ?: return
        if (!running) return
        val el = (System.nanoTime() - phaseStartNs) / 1e9
        if (el >= s.secs) endPhase()
    }

    private fun endPhase() {
        val s = cur ?: return
        running = false
        handler.removeCallbacks(timerRun)
        Choreographer.getInstance().removeFrameCallback(vsyncCb)

        val wall = (System.nanoTime() - phaseStartNs) / 1e9
        val cpu = (Debug.threadCpuTimeNanos() - phaseStartCpu) / 1e9
        val st = stats
        val f = st.frames.coerceAtLeast(1)
        val cpuUsPerFrame = cpu / f * 1e6

        note(
            String.format(
                Locale.US,
                "RESULT phase=%-11s pets=%d wall=%.2fs frames=%d fps=%.2f " +
                    "p50=%.2fms p95=%.2fms p99=%.2fms draw=%.3fms/frame " +
                    "cpu=%.2f%% cpuPerFrame=%.3fms",
                s.name, s.pets, wall, st.frames, st.frames / wall,
                st.percentile(0.50) / 1e6, st.percentile(0.95) / 1e6, st.percentile(0.99) / 1e6,
                st.drawNanos / 1e6 / f, cpu / wall * 100.0, cpuUsPerFrame / 1000.0
            )
        )

        beginPhase(specIdx + 1)
    }

    // ------------------------------------------------------------ 输出

    private fun note(line: String) {
        Log.i(TAG, line)
        results.add(line)
    }

    private fun finishUp() {
        view.liveStats = null
        view.hud = "DONE"
        view.invalidate()

        Log.i(TAG, "SUMMARY_BEGIN")
        for (r in results) Log.i(TAG, r)
        Log.i(TAG, "SUMMARY_END")

        try {
            val dir = getExternalFilesDir(null)
                ?: File(filesDir, "out").also { it.mkdirs() }
            val f = File(dir, "perf.txt")
            f.writeText(results.joinToString("\n") + "\n")
            Log.i(TAG, "WROTE ${f.absolutePath}")
        } catch (e: Exception) {
            Log.i(TAG, "WRITE_FAIL ${e.message}")
        }
    }
}
