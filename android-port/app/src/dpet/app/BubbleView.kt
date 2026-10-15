package dpet.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.View

/**
 * 角色头顶的台词气泡。
 *
 * 单独占一个 `FLAG_NOT_TOUCHABLE` 的悬浮窗 —— 为什么不跟宠物画在同一个 View 里：
 * 气泡比宠物宽得多（260dp vs 宠物约 130dp），合在一个窗口就等于把宠物窗口
 * 横向撑到 260dp，那一大片透明区域会把下层 app 的触摸全吃掉。
 * 拆成"可触摸的宠物窗口 + 完全不吃触摸的气泡窗口"是两个诉求同时满足的唯一办法。
 *
 * 绘制逐条对齐桌面版 `Bubble.paintEvent`：
 * * 气泡本体与尾巴**先合并成一个轮廓再描边**。分两个子路径时尾巴底边与气泡底边
 *   是同一条线，会被描两次（一条更深的横线穿过尾巴根部）。
 * * 文字基线用 `FontMetrics.ascent` 定位，不是"行高减一个经验常数"——
 *   多行时上下留白才对称。
 */
class BubbleView(context: Context) : View(context) {

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = context.dpF(1f)
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(238, 244, 255)
        textSize = context.sp(13.5f)
    }

    private val path = Path()
    private val bodyRect = RectF()
    private var lines: List<String> = emptyList()
    private var padX = 0f
    private var padY = 0f
    private var tail = 0f
    private var radius = 0f

    /**
     * 尾巴尖的 x（相对气泡左边缘，px）。负数 = 居中。
     *
     * 手机屏幕上宠物默认就待在右下角，气泡按锚点居中摆必然被屏幕边缘推回来，
     * 此时尾巴如果还画在气泡正中，就指不到宠物头上了。调用方按
     * "锚点 x − 气泡 x" 算一个偏移进来，尾巴就始终指着它。
     */
    var tailX: Float = -1f

    init {
        fillPaint.color = Color.argb(240, 30, 39, 62)
        strokePaint.color = Color.argb(170, 126, 178, 255)
        padX = context.dpF(13f)
        padY = context.dpF(9f)
        tail = context.dpF(7f)
        radius = context.dpF(11f)
    }

    /** 字体行高（px），给 Service 算窗口尺寸用 */
    val lineHeight: Float get() = textPaint.fontMetrics.let { it.descent - it.ascent }

    /**
     * 按文本算气泡该占多大，并记下折行结果。返回 `[w, h]`（含尾巴）。
     *
     * 折行是**逐字符累加**而不是按空格断词 —— 中文没有词边界，
     * 按空格断会得到一整行永远不换的字符串。
     */
    fun layout(text: String, maxWidthPx: Int): IntArray {
        val avail = maxWidthPx - padX * 2
        val out = ArrayList<String>()
        var cur = StringBuilder()
        for (ch in text) {
            val cand = cur.toString() + ch
            if (textPaint.measureText(cand) <= avail || cur.isEmpty()) {
                cur.append(ch)
            } else {
                out.add(cur.toString())
                cur = StringBuilder().append(ch)
            }
        }
        if (cur.isNotEmpty()) out.add(cur.toString())
        if (out.isEmpty()) out.add("")

        lines = out
        val fm = textPaint.fontMetrics
        var maxW = 0f
        for (l in out) maxW = Math.max(maxW, textPaint.measureText(l))
        val w = Math.max(maxW + padX * 2, context.dpF(76f))
        val h = (fm.descent - fm.ascent) * out.size + padY * 2 + tail
        return intArrayOf(Math.ceil(w.toDouble()).toInt(), Math.ceil(h.toDouble()).toInt())
    }

    override fun onDraw(canvas: Canvas) {
        if (lines.isEmpty()) return
        val w = width.toFloat()
        val h = height - tail

        path.reset()
        val body = Path().apply {
            bodyRect.set(strokePaint.strokeWidth / 2f, strokePaint.strokeWidth / 2f,
                w - strokePaint.strokeWidth / 2f, h - strokePaint.strokeWidth / 2f)
            addRoundRect(bodyRect, radius, radius, Path.Direction.CW)
        }
        val cx = if (tailX >= 0f) tailX.coerceIn(context.dpF(16f), w - context.dpF(16f)) else w / 2f
        val tailPath = Path().apply {
            moveTo(cx - context.dpF(7f), h - context.dpF(2f))    // 略往上咬进本体，保证并集连续
            lineTo(cx, h + tail - context.dpF(1f))
            lineTo(cx + context.dpF(7f), h - context.dpF(2f))
            close()
        }
        path.op(body, tailPath, Path.Op.UNION)           // 并集：接缝处只描一次

        canvas.drawPath(path, fillPaint)
        canvas.drawPath(path, strokePaint)

        val fm = textPaint.fontMetrics
        val lh = fm.descent - fm.ascent
        for ((i, line) in lines.withIndex()) {
            canvas.drawText(line, padX, padY + i * lh - fm.ascent, textPaint)
        }
    }
}
