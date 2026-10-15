package dpet.verify

import dpet.core.MiniJson
import dpet.core.MotionSet
import dpet.core.padFor
import dpet.core.scaleFor
import java.io.File

/**
 * 动效引擎的 JVM 侧采样器。
 *
 * 采样口径与 Python 版 tools/motion_regression.py **逐行对齐**：
 * 同样的素材顺序、同样的 STEPS=150、同样的 SCALES 四档、同样的负时间探点。
 * 这样两侧输出的每一行都能一一对上，比对才有意义。
 *
 * 数值一律写成 IEEE-754 的原始位模式（无符号十进制）。
 * 理由：Python 的 float.hex() 产出 0x0.0p+0，Java 的 Double.toHexString()
 * 产出 0x0.0p0 —— 差一个指数符号，字符串直接比会假报差异。位模式没有这个问题，
 * 而且能精确还原 ULP 距离。
 */
private val SCALES = doubleArrayOf(0.5, 1.0, 460.0 / 280.0, 2.0)
private val HEIGHTS = intArrayOf(80, 90, 130, 190, 280, 340, 380, 460, 520, 560)
private const val STEPS = 150

private fun bits(d: Double): String = java.lang.Long.toUnsignedString(d.toRawBits())

private fun appendParams(
    sb: StringBuilder, name: String, t: Double, scale: Double, r: DoubleArray
) {
    sb.append("params\t").append(name).append('\t')
        .append(bits(t)).append('\t').append(bits(scale)).append('\t')
        .append(bits(r[0])).append('\t').append(bits(r[1])).append('\t')
        .append(bits(r[2])).append('\t').append(bits(r[3])).append('\t')
        .append(bits(r[4])).append('\n')
}

fun main(args: Array<String>) {
    if (args.size < 2) {
        System.err.println("用法: MotionVerify <actions.json> <out.tsv>")
        kotlin.system.exitProcess(2)
    }

    val root = MiniJson.parseFile(args[0]) as Map<*, *>
    val motions = root["motions"] as? Map<*, *>
    val assets = root["assets"] as? Map<*, *>

    val vis = HashMap<String, Double>()
    if (assets != null) {
        for ((k, v) in assets) {
            val name = k as String
            val m = v as Map<*, *>
            vis[name] = (m["visual_scale"] as? Double) ?: 1.0
        }
    }

    val set = MotionSet(motions, vis)
    val sb = StringBuilder(1 shl 21)

    for (n in set.names()) {
        sb.append("cycle\t").append(n).append('\t').append(bits(set.cycle(n))).append('\n')
        sb.append("visual\t").append(n).append('\t')
            .append(bits(set.visualScale(n))).append('\n')
    }
    for (h in HEIGHTS) {
        sb.append("pad\t").append(h).append('\t').append(padFor(h)).append('\n')
        sb.append("scale_for\t").append(h).append('\t')
            .append(bits(scaleFor(h.toDouble()))).append('\n')
    }
    for (n in set.names()) {
        val cyc = set.cycle(n)
        for (i in 0..STEPS) {
            val t = cyc * 3.0 * i / STEPS
            for (sc in SCALES) appendParams(sb, n, t, sc, set.params(n, t, sc))
        }
        appendParams(sb, n, -0.5, 1.0, set.params(n, -0.5, 1.0))
    }

    File(args[1]).writeText(sb.toString(), Charsets.UTF_8)
    println("Kotlin 采样完成：${set.names().size} 个素材 → ${args[1]}")
    if (set.unknown.isNotEmpty()) {
        println("警告：出现未识别原语 ${set.unknown}")
    }
}
