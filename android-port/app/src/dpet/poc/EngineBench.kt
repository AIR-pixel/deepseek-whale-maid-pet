package dpet.poc

import dpet.core.MotionSet
import java.util.Locale

/**
 * 引擎微基准 —— **成批测量**，全屏基准与悬浮窗基准共用同一份实现。
 *
 * 为什么不放渲染循环里逐帧计时：单次 `params()` 只有几微秒，比线程调度粒度还短，
 * 有 RenderThread / SurfaceFlinger 抢核时，窗口内的一次抢占就能把结果放大几十倍。
 * 实测在渲染循环里量出来是 ~583 µs/次，而成批量是 ~8.2 µs/次 —— 差 70 倍，
 * 全部来自抢占。所以这里一次计时覆盖上万次调用，让真实工作占绝对主导。
 *
 * 返回的是"要写进结果文件的整行"，由调用方决定落到哪个 tag / 哪个文件 ——
 * 这样 Service 和 Activity 不必各抄一份测量逻辑。
 */
object EngineBench {

    /** 顺带量 `System.nanoTime()` 自身开销，用于判断是否时钟本身就慢（反证）。 */
    private fun clock(): String {
        val n = 200_000
        var acc = 0L
        for (i in 0 until 2000) acc += System.nanoTime()      // 预热
        val t0 = System.nanoTime()
        for (i in 0 until n) acc += System.nanoTime()
        val ns = System.nanoTime() - t0
        return String.format(
            Locale.US, "RESULT phase=clock     calls=%d nsPerCall=%.1f sink=%d",
            n + 1, ns.toDouble() / (n + 1), acc
        )
    }

    private fun fmt(v: Double): String = String.format(Locale.US, "%.4f", v)

    fun run(motion: MotionSet, iters: Int = 20000): List<String> {
        val out = ArrayList<String>(2)
        out.add(clock())

        val names = motion.names()
        var sink = 0.0
        for (nm in names) sink += motion.params(nm, 0.5, 1.0)[0]   // 预热，让 JIT 先编译

        val t0 = System.nanoTime()
        for (i in 0 until iters) {
            val tt = (i % 1000) * 0.004
            for (nm in names) sink += motion.params(nm, tt, 1.0)[0]
        }
        val ns = System.nanoTime() - t0
        val calls = iters.toLong() * names.size
        val perCall = ns.toDouble() / calls

        out.add(
            String.format(
                Locale.US,
                "RESULT phase=engine    states=%d calls=%d nsPerCall=%.1f usPerCall=%.4f " +
                    "usPerFrame1=%s usPerFrame8=%s sink=%.6f",
                names.size, calls, perCall, perCall / 1000.0,
                fmt(perCall / 1000.0), fmt(perCall * 8 / 1000.0), sink
            )
        )
        return out
    }
}
