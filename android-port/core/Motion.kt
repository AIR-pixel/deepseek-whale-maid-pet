package dpet.core

import kotlin.math.PI
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/**
 * 程序化动效引擎 —— Python 版 src/motion.py 的逐位等价移植。
 *
 * 移植纪律
 * --------
 * 原实现的铁律是「输出一个数值都没变」，容差 0 而不是 1e-6。跨语言照抄时，
 * 这句话不能直接照搬（两边的 libm 实现不同），但**运算顺序必须逐字保持**，
 * 剩下的差异才有资格被称为"不可约的 ULP 噪声"。
 *
 * 为此有三处刻意"不写得更漂亮"的地方，每一处都有实测依据：
 *
 * 1. `easeIn` 用 `pow(x, 3.0)` 而**不是** `x * x * x`。
 *    实测 1182 个真实样本：`pow` 与 CPython 的 `x ** 3` 逐位相同率 100%，
 *    而 `x * x * x` 只有 76.31%（最大 1 ULP）。原因是 CPython 的 `float ** int`
 *    走的也是 C 库 `pow()`，所以"看起来更快的写法"反而偏离了基准。
 *    → 见 verify/SinProbe.java 的实测输出。
 *
 * 2. `padFor` 用 `rint` 而不是 `round`。Python 的 `round()` 是**银行家舍入**
 *    （半值取偶），Kotlin 的 `Math.round` 是半值远离零。当前 10 档高度都避开了
 *    .5，但用户滚轮能停在任意高度，迟早会撞上 —— 到那时差的就是整 1px 边距。
 *
 * 3. `pyMod` 手写而不是直接用 `%`。Python 的 `%` 是 floor 语义，Kotlin 是
 *    truncated 语义，负数上结论相反（Python -0.5 % 3.0 = 2.5，Kotlin 得 -0.5）。
 *    `params()` 里虽然把 t 钳到了非负，但 `raw()` 是公开入口，不能留这个地雷。
 *
 * 曲线是数据、引擎只解释执行 —— 这部分设计与原实现完全一致，
 * 连原语集合（const / sine / freq / pulse_sum / sink / hop / ref）都没变。
 */
val TAU: Double = PI * 2
const val REF_H = 280.0
const val SCALE_MIN = 0.5
const val DEFAULT_CYCLE = 3.0

val ORDER: List<String> = listOf("dy", "dx", "sx", "sy", "rot")

val BASE: Map<String, Double> = linkedMapOf(
    "dy" to 0.0, "dx" to 0.0, "sx" to 1.0, "sy" to 1.0, "rot" to 0.0
)

private val DEFAULT_PARAMS = doubleArrayOf(0.0, 0.0, 1.0, 1.0, 0.0)

/** Python 语义的取模（floor），与 CPython 的 float_rem 一致 */
private fun pyMod(a: Double, b: Double): Double {
    var m = a % b
    if (m != 0.0 && ((b < 0.0) != (m < 0.0))) m += b
    return m
}

private fun sinT(t: Double, period: Double, phase: Double = 0.0): Double =
    sin(TAU * t / period + phase)

/** 周期脉冲：一个周期内前 duty 比例为 1，其余为 0 */
private fun pulse(t: Double, period: Double, duty: Double): Double =
    if (pyMod(t, period) / period < duty) 1.0 else 0.0

/** 银行家舍入 —— 对齐 Python 的 round()。kotlin.math 没有 rint，用 java.lang.Math。 */
private fun pyRound(x: Double): Double = Math.rint(x)

private fun easeIn(x: Double): Double = Math.pow(x, 3.0)

private fun easeOut(x: Double): Double = 1.0 - Math.pow(1.0 - x, 3.0)

// ---------------------------------------------------------------- 原语

/** 中间量：save 存、ref 取。两个键名分开是刻意的（见原实现注释）。 */
private class Ctx {
    val sigs = HashMap<String, Double>()
    val chans = HashMap<String, Double>()
}

private class Term(private val m: Map<String, Any?>) {
    val key: String? get() = m["k"] as? String
    val save: String? get() = m["save"] as? String

    fun req(k: String): Double = m[k] as? Double
        ?: throw IllegalArgumentException("缺少必需字段 '$k'")

    fun d(k: String, def: Double): Double = (m[k] as? Double) ?: def

    fun dOrNull(k: String): Double? = m[k] as? Double

    fun str(k: String): String? = m[k] as? String

    fun has(k: String): Boolean = m.containsKey(k)

    /** pulse_sum 的 items：[[周期, 占空比], ...] */
    @Suppress("UNCHECKED_CAST")
    fun pairs(k: String): List<List<Any?>> = m[k] as? List<List<Any?>>
        ?: throw IllegalArgumentException("缺少数组字段 '$k'")
}

private fun evConst(term: Term, t: Double, ch: String, ctx: Ctx): Pair<Double, Double> {
    val v = term.d("v", 0.0)
    return v to v
}

private fun evSine(term: Term, t: Double, ch: String, ctx: Ctx): Pair<Double, Double> {
    val raw = sinT(t, term.req("period"), term.d("phase", 0.0))
    return raw to raw * term.d("amp", 1.0)
}

private fun evFreq(term: Term, t: Double, ch: String, ctx: Ctx): Pair<Double, Double> {
    val raw = sin(term.req("omega") * t)
    return raw to raw * term.d("amp", 1.0)
}

private fun evPulseSum(term: Term, t: Double, ch: String, ctx: Ctx): Pair<Double, Double> {
    var total = 0.0
    for (pair in term.pairs("items")) {
        total += pulse(t, pair[0] as Double, pair[1] as Double)
    }
    val raw = min(total, term.d("max", 1.0))
    return raw to raw * term.d("amp", 1.0)
}

/**
 * 打瞌睡：0.78 的时间缓慢低头（ease-in），剩下 0.22 猛地抬头（ease-out）。
 * 段点写死在引擎里而不是做成参数 —— 它就是这个动作的形状。
 */
private fun evSink(term: Term, t: Double, ch: String, ctx: Ctx): Pair<Double, Double> {
    val period = term.req("period")
    val ph = pyMod(t, period) / period
    val raw = if (ph < 0.78) {
        easeIn(ph / 0.78)
    } else {
        // 注意：不能化简成 (1-x)**3。浮点上 1-(1-a) 不一定等于 a，
        // 原实现逐字写的是 1.0 - easeOut(...)，这里照抄。
        1.0 - easeOut((ph - 0.78) / 0.22)
    }
    return raw to raw * term.d("amp", 1.0)
}

/**
 * 蹲下蓄力（0~0.10）→ 腾空（0.10~0.80）→ 落地缓冲（0.80~1.0）。
 * 输出哪一路由所在通道决定；段点同样写死。
 */
private fun evHop(term: Term, t: Double, ch: String, ctx: Ctx): Pair<Double, Double> {
    val period = term.req("period")
    val ph = pyMod(t, period) / period
    when (ch) {
        "dy" -> {
            if (ph < 0.10) return 0.0 to term.d("crouch_amp", 0.0) * (ph / 0.10)
            if (ph < 0.80) {
                val k = (ph - 0.10) / 0.70
                return 0.0 to -sin(k * PI) * term.d("amp", 0.0)
            }
            return 0.0 to 0.0
        }
        "sx" -> {
            if (ph < 0.10) return 0.0 to term.d("crouch_sx", 0.0) * (ph / 0.10)
            if (ph < 0.80) return 0.0 to 0.0
            val k = sin((ph - 0.80) / 0.20 * PI)
            return 0.0 to term.d("land_sx", 0.0) * k
        }
        "sy" -> {
            if (ph < 0.10) return 0.0 to -term.d("crouch_sy", 0.0) * (ph / 0.10)
            if (ph < 0.80) return 0.0 to 0.0
            val k = sin((ph - 0.80) / 0.20 * PI)
            return 0.0 to -term.d("land_sy", 0.0) * k
        }
    }
    return 0.0 to 0.0
}

/** ref 有两种引用方式：sig 取中间量，ch 取已算完的通道累计增量 */
private fun evRef(term: Term, t: Double, ch: String, ctx: Ctx): Pair<Double, Double> {
    val amp = term.d("amp", 1.0)
    val sig = term.str("sig")
    if (sig != null) {
        val v = ctx.sigs[sig]
            ?: throw NoSuchElementException("引用了未定义的信号 '$sig'")
        return 0.0 to v * amp
    }
    val chName = term.str("ch")
        ?: throw NoSuchElementException("ref 既没有 sig 也没有 ch")
    val v = ctx.chans[chName]
        ?: throw NoSuchElementException(
            "引用了尚未求值的通道 '$chName'（顺序必须是 ${ORDER.joinToString(" → ")}）"
        )
    return 0.0 to v * amp
}

private typealias Primitive = (Term, Double, String, Ctx) -> Pair<Double, Double>

private val PRIMITIVES: Map<String, Primitive> = mapOf(
    "const" to ::evConst,
    "sine" to ::evSine,
    "freq" to ::evFreq,
    "pulse_sum" to ::evPulseSum,
    "sink" to ::evSink,
    "hop" to ::evHop,
    "ref" to ::evRef,
)

// ---------------------------------------------------------------- 动作集合

private class MotionDef(
    val cycle: Double,
    val channels: Map<String, List<Term>>,
    val rawChannels: Map<String, List<Any?>>,
    val termDefs: Map<String, Any?>,
)

@Suppress("UNCHECKED_CAST")
private fun asMap(m: Any?): Map<String, Any?> = (m as? Map<*, *>)?.let {
    it as Map<String, Any?>
} ?: emptyMap()

@Suppress("UNCHECKED_CAST")
private fun asRawMap(m: Any?): Map<*, *> = (m as? Map<*, *>) ?: emptyMap<Any?, Any?>()

private fun expand(terms: List<Any?>, defs: Map<String, Any?>): List<Term> {
    val out = ArrayList<Term>(terms.size)
    for (t in terms) {
        val m = asRawMap(t)
        val key = m["\$def"] as? String
        if (key == null) {
            out.add(Term(asMap(m)))
        } else {
            val d = defs[key]
                ?: throw NoSuchElementException("引用了不存在的原语定义: $key")
            out.add(Term(asMap(d)))
        }
    }
    return out
}

/** 展开 inherit 链。子定义覆盖父定义，可只写 {"inherit": "父名"}。 */
private fun resolve(motions: Map<*, *>): Map<String, MotionDef> {
    val out = HashMap<String, MotionDef>()

    fun build(name: String, seen: Set<String>): MotionDef {
        out[name]?.let { return it }
        if (name in seen) throw IllegalStateException("动作继承成环: $name")
        val src = motions[name] as? Map<*, *>
            ?: throw NoSuchElementException("继承了不存在的动作: $name")

        val parent = src["inherit"] as? String
        var baseCycle = DEFAULT_CYCLE
        var baseRaw: Map<String, List<Any?>> = emptyMap()
        var baseDefs: Map<String, Any?> = emptyMap()
        if (parent != null) {
            val par = build(parent, seen + name)
            baseCycle = par.cycle
            baseRaw = par.rawChannels
            baseDefs = par.termDefs
        }

        val channels = LinkedHashMap(baseRaw)
        asRawMap(src["channels"]).forEach { (k, v) ->
            channels[k as String] = (v as? List<Any?>) ?: emptyList()
        }

        val termDefs = LinkedHashMap(baseDefs)
        asRawMap(src["defs"]).forEach { (k, v) -> termDefs[k as String] = v }

        val expanded = LinkedHashMap<String, List<Term>>()
        for ((ch, terms) in channels) expanded[ch] = expand(terms, termDefs)

        val cycle = (src["cycle"] as? Double) ?: baseCycle
        val d = MotionDef(cycle, expanded, channels, termDefs)
        out[name] = d
        return d
    }

    for (k in motions.keys) build(k as String, emptySet())
    return out
}

/**
 * 一组素材的动效定义。构造后不可变，整体替换即可热加载 ——
 * 这正是"从远端接收新动作"的基础。
 */
class MotionSet(motions: Map<*, *>?, visualScales: Map<String, Double>? = null) {

    private val defs: Map<String, MotionDef> = resolve(motions ?: emptyMap<Any?, Any?>())
    private val vis: Map<String, Double> = visualScales ?: emptyMap()

    /** 不认识的原语名 —— 旧版本收到新动作时列为空，不会崩 */
    val unknown: List<String> = defs.values
        .flatMap { d -> d.channels.values.flatten() }
        .mapNotNull { it.key }
        .filter { it !in PRIMITIVES }
        .distinct()
        .sorted()

    fun names(): List<String> = defs.keys.sorted()

    fun has(name: String): Boolean = defs.containsKey(name)

    fun cycle(name: String): Double = defs[name]?.cycle ?: DEFAULT_CYCLE

    fun visualScale(name: String): Double = vis[name] ?: 1.0

    /** 返回该素材在 t 时刻**未缩放**的 (dx, dy, sx, sy, rot) */
    fun raw(name: String, t: Double): DoubleArray {
        val d = defs[name] ?: return DEFAULT_PARAMS.copyOf()
        val total = LinkedHashMap(BASE)
        val ctx = Ctx()
        for (ch in ORDER) {
            var acc = BASE[ch]!!
            for (term in d.channels[ch] ?: emptyList()) {
                val fn = PRIMITIVES[term.key] ?: continue   // 不认识的原语直接跳过
                val (rawV, contrib) = fn(term, t, ch, ctx)
                val save = term.save
                if (save != null) {
                    // 默认存"该原语对本通道的贡献值"（= raw × amp）；
                    // save_scale 用来显式换取别的口径（eat 的裸 sin）。
                    val k = term.dOrNull("save_scale") ?: term.d("amp", 1.0)
                    ctx.sigs[save] = rawV * k
                }
                acc += contrib
            }
            total[ch] = acc
            ctx.chans[ch] = acc
        }
        return doubleArrayOf(
            total["dx"]!!, total["dy"]!!, total["sx"]!!, total["sy"]!!, total["rot"]!!
        )
    }

    /** 缩放由 height 推出的 scale 决定；旋转是角度，不参与缩放。 */
    fun params(name: String, t: Double, scale: Double = 1.0): DoubleArray {
        val r = raw(name, max(t, 0.0))
        return doubleArrayOf(r[0] * scale, r[1] * scale, r[2], r[3], r[4])
    }

    fun cycles(): Map<String, Double> = defs.mapValues { it.value.cycle }

    fun visualScales(): Map<String, Double> = vis.toMap()
}

/** 由角色高度推出幅度缩放系数（带下限） */
fun scaleFor(height: Double): Double = max(height / REF_H, SCALE_MIN)

/** 给定角色高度，算出需要预留的边距（覆盖跳跃位移 + 旋转外溢） */
fun padFor(height: Int): Int = pyRound(12 + height * 0.042).toInt()
