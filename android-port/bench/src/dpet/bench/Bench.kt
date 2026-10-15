package dpet.bench

import dpet.core.MiniJson
import dpet.core.MotionSet
import java.io.File
import java.util.Locale

/**
 * 设备侧基准。
 *
 * 走 app_process + dex jar，不需要安装 APK —— 在 MIUI/HyperOS 上
 * adb install 会被「USB 安装」开关拦掉（INSTALL_FAILED_USER_RESTRICTED），
 * 而 app_process 不受影响。这样至少能在**真实 ARM64 的 ART** 上
 * 量出引擎开销、并复核 Math.sin 的位级行为。
 *
 * 用法：
 *   Bench <actions.json> [sin_calls.tsv] [sin_out.tsv]
 */

private fun orderedBits(b: Long): Long = if (b < 0L) Long.MIN_VALUE - b else b

private fun ulpDistance(a: Long, b: Long): Long {
    val x = orderedBits(a)
    val y = orderedBits(b)
    return if (x >= y) x - y else y - x
}

private fun benchEngine(path: String) {
    val root = MiniJson.parseFile(path) as Map<*, *>
    val set = MotionSet(root["motions"] as? Map<*, *>, visualScalesOf(root))
    val names = set.names()

    // 预热：让 JIT 先编译掉解释执行的开销
    var sink = 0.0
    for (nm in names) sink += set.params(nm, 0.5, 1.0)[0]

    val iters = 200_000
    val t0 = System.nanoTime()
    for (i in 0 until iters) {
        val tt = (i % 1000) * 0.004
        for (nm in names) sink += set.params(nm, tt, 1.0)[0]
    }
    val ns = System.nanoTime() - t0
    val calls = iters.toLong() * names.size

    println(
        String.format(
            Locale.US,
            "ENGINE arch=%s cores=%d states=%d calls=%d nsPerCall=%.1f usPerCall=%.4f sink=%.6f",
            System.getProperty("os.arch") ?: "?",
            Runtime.getRuntime().availableProcessors(),
            names.size, calls, ns.toDouble() / calls, ns.toDouble() / calls / 1000.0, sink
        )
    )

    // 一帧的开销：8 个状态各算一次（stress 阶段的真实工作量）
    val frames = 100_000
    val t1 = System.nanoTime()
    for (i in 0 until frames) {
        val tt = i * 0.0001
        for (nm in names) sink += set.params(nm, tt, 1.0)[4]
    }
    val ns2 = System.nanoTime() - t1
    println(
        String.format(
            Locale.US,
            "PERFRAME states=%d frames=%d nsPerFrame=%.1f usPerFrame=%.3f",
            names.size, frames, ns2.toDouble() / frames, ns2.toDouble() / frames / 1000.0
        )
    )
}

private fun visualScalesOf(root: Map<*, *>): Map<String, Double> {
    val vis = HashMap<String, Double>()
    val assets = root["assets"] as? Map<*, *> ?: return vis
    for ((k, v) in assets) {
        vis[k as String] = ((v as? Map<*, *>)?.get("visual_scale") as? Double) ?: 1.0
    }
    return vis
}

/** 拿 Python 记录的真实 sin 参数集，在设备上重算并逐位比对。 */
private fun sinSnapshot(inPath: String, outPath: String) {
    val lines = File(inPath).readLines()
    val sb = StringBuilder(1 shl 20)
    var same = 0L
    var diff = 0L
    var maxUlp = 0L
    var seen = 0L

    for (ln in lines) {
        if (ln.isBlank()) continue
        val parts = ln.trim().split('\t')
        if (parts.size < 2) continue
        val arg = java.lang.Double.parseDouble(parts[0].trim())
        val pyBits = parts[1].trim().toLong()
        val kb = Math.sin(arg).toRawBits()
        val d = ulpDistance(kb, pyBits)
        if (d == 0L) same++ else diff++
        if (d > maxUlp) maxUlp = d
        seen++
        sb.append(parts[0].trim()).append('\t').append(kb).append('\t').append(pyBits).append('\n')
    }

    File(outPath).writeText(sb.toString(), Charsets.UTF_8)
    println(
        String.format(
            Locale.US,
            "SIN arch=%s total=%d identical=%d differing=%d maxUlp=%d matchRate=%.4f%%",
            System.getProperty("os.arch") ?: "?", seen, same, diff, maxUlp,
            if (seen == 0L) 0.0 else same * 100.0 / seen
        )
    )
}

fun main(args: Array<String>) {
    if (args.isEmpty()) {
        System.err.println("用法: Bench <actions.json> [sin_calls.tsv] [sin_out.tsv]")
        kotlin.system.exitProcess(2)
    }
    // 统一到 UTC，避免设备时区影响任何时间相关分支（当前引擎不依赖时间，纯保险）
    System.setProperty("user.timezone", "UTC")

    benchEngine(args[0])
    if (args.size >= 3) sinSnapshot(args[1], args[2])
}
