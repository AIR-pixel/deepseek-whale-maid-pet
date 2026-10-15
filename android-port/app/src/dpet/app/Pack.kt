package dpet.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import dpet.core.MiniJson
import dpet.core.MotionSet
import dpet.core.padFor

/**
 * 内容包：`content/actions.json` + 立绘。
 *
 * 与 bench 版那个「最小可用子集」的区别是**这里把 states 也读进来了** ——
 * 状态机要靠 states 的 frames / temp / dur / weight 决定"能演什么、演多久、抽签权重"。
 * bench 版只需要动效本身，所以刻意不带这部分。
 *
 * 解析失败一律抛异常，由调用方兜住 —— 内容包坏了就退回内置素材，
 * 不能让一张读不出来的图把整个服务拖垮（桌面版 `_load_assets` 同一条纪律）。
 */
class Pack private constructor(
    val motion: MotionSet,
    private val src: LinkedHashMap<String, Bitmap>,
    val states: LinkedHashMap<String, StateMeta>,
    val contentVersion: Int,
    val generator: String
) {

    /** 按目标高度预缩放的显示用位图 */
    private val shown = LinkedHashMap<String, Bitmap>()

    /** 每帧的逻辑尺寸 [w, h]（与桌面版 lsize 同口径，不含 dpr） */
    val lsize = LinkedHashMap<String, IntArray>()

    /** 动效余量：覆盖跳跃位移 + 旋转外溢 */
    var pad = 0
        private set

    var targetHeightPx = 0
        private set

    class StateMeta(
        val frames: List<String>,
        val temp: Boolean,
        val durMin: Double,
        val durMax: Double,
        val weight: Int,
        val cue: String?,
        val lines: List<String>
    )

    val frameNames: List<String> get() = src.keys.toList()

    fun has(name: String): Boolean = src.containsKey(name)

    fun bitmap(name: String): Bitmap? = shown[name]

    fun size(name: String): IntArray? = lsize[name]

    /** 一帧的显示尺寸（含动效余量），用于算悬浮窗该开多大 */
    fun paddedSize(name: String): IntArray {
        val s = lsize[name] ?: return intArrayOf(1, 1)
        return intArrayOf(s[0] + pad * 2, s[1] + pad * 2)
    }

    fun stateMeta(name: String): StateMeta? = states[name]

    /** 能参与待机抽签的状态：weight > 0 的才上桌 */
    fun idlePool(): List<Pair<String, Int>> {
        val out = ArrayList<Pair<String, Int>>()
        for ((name, meta) in states) if (meta.weight > 0) out.add(name to meta.weight)
        return out
    }

    /** 眨眼用的两帧；缺任意一帧就返回 null（缺图不该让程序崩） */
    fun blinkFrames(): Pair<String, String>? =
        if (has("idle_open") && has("idle_blink")) "idle_open" to "idle_blink" else null

    fun firstFrame(): String =
        if (has("idle_open")) "idle_open" else (frameNames.firstOrNull() ?: "")

    /**
     * 按配置高度重算所有帧的显示尺寸。
     *
     * 算术与桌面版 `_rescale` 逐字一致：`fh = round(h * visual_scale)`，
     * 宽度按原图比例推。round 用的是银行家舍入（[Math.rint]），不是 [Math.round] ——
     * 见 core/Motion.kt 里 `padFor` 的三条移植纪律。
     */
    fun rescale(heightPx: Int) {
        targetHeightPx = heightPx
        shown.clear()
        lsize.clear()
        var maxH = 1
        for ((name, bmp) in src) {
            val vs = motion.visualScale(name)
            val fh = Math.max(1, Math.rint(heightPx * vs).toInt())
            val nw = Math.max(1, Math.rint(bmp.width.toDouble() * fh / bmp.height).toInt())
            val scaled = if (nw == bmp.width && fh == bmp.height) bmp
            else Bitmap.createScaledBitmap(bmp, nw, fh, true)
            shown[name] = scaled
            lsize[name] = intArrayOf(nw, fh)
            if (fh > maxH) maxH = fh
        }
        pad = padFor(maxH)
    }

    fun release() {
        for (b in shown.values) if (!b.isRecycled) b.recycle()
        for (b in src.values) if (!b.isRecycled) b.recycle()
        shown.clear()
        lsize.clear()
    }

    companion object {

        /** 立绘放在 assets 的哪个目录下 */
        private const val ASSET_DIR = "pet"
        private const val CONTENT = "content/actions.json"

        fun load(ctx: Context): Pack {
            val text = ctx.assets.open(CONTENT).use { it.readBytes().toString(Charsets.UTF_8) }
            val root = MiniJson.parse(text) as? Map<*, *>
                ?: throw IllegalStateException("actions.json 不是一个对象")

            val assetsMap = (root["assets"] as? Map<*, *>) ?: emptyMap<Any?, Any?>()
            val scaleMap = LinkedHashMap<String, Double>()
            val src = LinkedHashMap<String, Bitmap>()

            for ((k, v) in assetsMap) {
                val name = k as? String ?: continue
                val m = v as? Map<*, *> ?: continue
                scaleMap[name] = (m["visual_scale"] as? Double) ?: 1.0
                // file 字段形如 "pet/idle_open.webp"，只取文件名 —— assets 目录已固定
                val file = (m["file"] as? String) ?: "$ASSET_DIR/$name.webp"
                val base = file.substringAfterLast('/')
                val bmp = decode(ctx, "$ASSET_DIR/$base")
                    ?: throw IllegalStateException("无法解码立绘: $base")
                src[name] = bmp
            }
            if (src.isEmpty()) throw IllegalStateException("内容包里一张立绘都没有")

            val states = LinkedHashMap<String, StateMeta>()
            val rawStates = (root["states"] as? Map<*, *>) ?: emptyMap<Any?, Any?>()
            for ((k, v) in rawStates) {
                val name = k as? String ?: continue
                val m = v as? Map<*, *> ?: continue
                val frames = (m["frames"] as? List<*>)
                    ?.mapNotNull { it as? String }
                    ?.filter { src.containsKey(it) }
                    ?: emptyList()
                if (frames.isEmpty()) continue          // 素材缺失的状态直接不登记

                var dMin = 0.0
                var dMax = 0.0
                (m["dur"] as? List<*>)?.let { d ->
                    if (d.size >= 2) {
                        dMin = (d[0] as? Double) ?: 0.0
                        dMax = (d[1] as? Double) ?: dMin
                    }
                }
                states[name] = StateMeta(
                    frames = frames,
                    temp = (m["temp"] as? Boolean) ?: false,
                    durMin = dMin,
                    durMax = dMax,
                    weight = (m["weight"] as? Double)?.toInt() ?: 0,
                    cue = m["cue"] as? String,
                    lines = (m["lines"] as? List<*>)?.mapNotNull { it as? String } ?: emptyList()
                )
            }
            if (states.isEmpty()) throw IllegalStateException("内容包里没有任何可用状态")

            return Pack(
                motion = MotionSet(root["motions"] as? Map<*, *>, scaleMap),
                src = src,
                states = states,
                contentVersion = (root["content_version"] as? Double)?.toInt() ?: 0,
                generator = (root["generator"] as? String) ?: "?"
            )
        }

        /** 立绘缺失时返回 null 而不是抛 —— 单帧读不出来不该拖垮整包 */
        private fun decode(ctx: Context, path: String): Bitmap? = try {
            ctx.assets.open(path).use { BitmapFactory.decodeStream(it) }
        } catch (_: Throwable) {
            null
        }
    }
}
