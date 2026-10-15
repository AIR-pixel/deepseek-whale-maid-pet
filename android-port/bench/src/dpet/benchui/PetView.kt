package dpet.benchui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.PorterDuff
import android.view.View
import dpet.core.MiniJson
import dpet.core.MotionSet
import dpet.core.padFor
import dpet.core.scaleFor

/**
 * 内容包最小可用子集：actions.json + 立绘。
 *
 * 只做 POC 需要的事：解析 motions / visual_scale、解码立绘、按目标高度预缩放。
 * 不含内容热加载、下载、states 状态机 —— 那些与「跑不跑得动」无关。
 *
 * 全屏基准与悬浮窗基准共用这一个类，所以它不能依赖任何 Activity。
 */
class Pack(ctx: Context) {

    val motion: MotionSet
    private val src = LinkedHashMap<String, Bitmap>()
    val shown = LinkedHashMap<String, Bitmap>()
    val lsize = LinkedHashMap<String, IntArray>()   // [w, h]
    var pad = 0
        private set

    init {
        val text = ctx.assets.open("content/actions.json").use {
            it.readBytes().toString(Charsets.UTF_8)
        }
        val root = MiniJson.parse(text) as Map<*, *>
        val assetsMap = (root["assets"] as? Map<*, *>) ?: emptyMap<Any?, Any?>()
        val vis = LinkedHashMap<String, Double>()

        for ((k, v) in assetsMap) {
            val name = k as String
            val m = v as Map<*, *>
            vis[name] = (m["visual_scale"] as? Double) ?: 1.0
            val file = m["file"] as String
            val bmp = ctx.assets.open(file).use { BitmapFactory.decodeStream(it) }
                ?: throw IllegalStateException("无法解码立绘: $file")
            src[name] = bmp
        }
        motion = MotionSet(root["motions"] as? Map<*, *>, vis)
    }

    val frameCount: Int get() = src.size

    /** 与桌面端 _rescale 同一套算术：fh = round(h * visual_scale)，宽度按原图比例 */
    fun rescale(heightPx: Int) {
        shown.clear()
        lsize.clear()
        var maxH = 1
        for ((name, bmp) in src) {
            val fh = maxOf(1, Math.rint(heightPx * motion.visualScale(name)).toInt())
            val nw = maxOf(1, Math.rint(bmp.width.toDouble() * fh / bmp.height).toInt())
            shown[name] = Bitmap.createScaledBitmap(bmp, nw, fh, true)
            lsize[name] = intArrayOf(nw, fh)
            if (fh > maxH) maxH = fh
        }
        pad = padFor(maxH)
    }
}

/**
 * 单阶段统计。
 *
 * 这里**刻意不统计"每帧调用一次引擎花了多久"** —— 单次调用只有几微秒，
 * 比线程调度粒度还短，在有 RenderThread / SurfaceFlinger 抢核的 UI 线程上，
 * 窗口内任何一次抢占都会把结果放大几十倍，量到的是抢占率不是引擎开销。
 * 引擎开销改由 [EngineBench.run] 成批测量（见那里的注释）。
 */
class PerfStats {
    var frames = 0L
    var drawNanos = 0L
    private var lastNs = 0L
    private val gaps = ArrayList<Long>(16384)
    private var sorted: LongArray? = null        // 排序结果缓存，见 percentile()

    fun noteFrame(now: Long) {
        if (lastNs != 0L) {
            gaps.add(now - lastNs)
            sorted = null                        // 新样本进来，缓存作废
        }
        lastNs = now
        frames++
    }

    /**
     * 取第 p 分位的帧间隔（纳秒）。
     *
     * 一次阶段结束会连着问 p50 / p95 / p99 三次，老写法每次都 `gaps.sorted()`
     * 重排一遍（几千个元素排三遍）。排序结果缓存到下一次采样为止。
     */
    fun percentile(p: Double): Long {
        if (gaps.isEmpty()) return 0L
        val s = sorted ?: gaps.toLongArray().apply { sort() }.also { sorted = it }
        val idx = Math.rint((s.size - 1) * p).toInt().coerceIn(0, s.size - 1)
        return s[idx]
    }
}

/**
 * 画布。逐行复刻桌面端 paintEvent 的变换链与锚点：
 *
 *   ax = x + lw/2, ay = y + lh        （脚底中心，呼吸时脚不动）
 *   世界矩阵 = T(ax+dx, ay+dy) · R(rot) · S(sx, sy) · T(-ax, -ay)
 *   最终     = 世界矩阵 · T(x, y)
 *
 * 作用到 bitmap 局部坐标就是 M = T(ax+dx,ay+dy)·R·S·T(-ax,-ay)·T(x,y)。
 * Android 的 postConcat 语义是 M' = other·M，所以按下标从内到外依次 post。
 */
class PetView(ctx: Context, private val pack: Pack) : View(ctx) {

    private val paint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
    private val bgPaint = Paint()
    private val hudPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 36f
        isFakeBoldText = true
    }
    private val m = Matrix()

    /** 基准逐个素材轮转展示用的顺序（Pack 里没有的会被跳过） */
    private val states = arrayOf(
        "idle_open", "work_keypress", "eat", "happy",
        "blindfold", "whale", "doze", "sleep"
    )

    var petCount = 1
    var t = 0.0
    var liveStats: PerfStats? = null
    var hud: String = ""
    var drawBg = true
    var margin = 16f
    var onFrameDone: (() -> Unit)? = null

    init {
        bgPaint.color = Color.rgb(14, 16, 22)
    }

    override fun onDraw(canvas: Canvas) {
        val drawT0 = System.nanoTime()
        val st = liveStats

        if (drawBg) {
            canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), bgPaint)
        } else {
            // 悬浮窗是 TRANSLUCENT 的，必须显式清成透明 —— 否则上一帧的像素会残留成拖影
            canvas.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR)
        }

        val n = petCount.coerceAtLeast(1)
        val slot = (width - margin * 2) / n

        for (i in 0 until n) {
            val name = states[i % states.size]
            val sz = pack.lsize[name] ?: continue
            val bmp = pack.shown[name] ?: continue
            val lw = sz[0]
            val lh = sz[1]

            val x = margin + slot * i + (slot - lw) / 2f
            val y = (height - lh - pack.pad).toFloat()

            val p = pack.motion.params(name, t + i * 0.37, scaleFor(lh.toDouble()))

            val dx = p[0]
            val dy = p[1]
            val sx = p[2]
            val sy = p[3]
            val rot = p[4]

            val ax = x + lw / 2.0f
            val ay = y + lh.toFloat()

            m.reset()
            m.postTranslate(x, y)                                  // 最内层
            m.postTranslate(-ax, -ay)
            m.postScale(sx.toFloat(), sy.toFloat())
            if (rot != 0.0) m.postRotate(rot.toFloat())
            m.postTranslate(ax + dx.toFloat(), ay + dy.toFloat())  // 最外层

            canvas.drawBitmap(bmp, m, paint)
        }

        if (hud.isNotEmpty()) canvas.drawText(hud, 28f, height - 64f, hudPaint)

        if (st != null) {
            st.drawNanos += System.nanoTime() - drawT0
            st.noteFrame(System.nanoTime())
        }
        onFrameDone?.invoke()
    }
}
