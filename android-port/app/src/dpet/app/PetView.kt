package dpet.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.PorterDuff
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import dpet.core.scaleFor
import kotlin.math.abs

/**
 * 宠物本体：渲染 + 手势。
 *
 * 渲染逐行复刻桌面版 `paintEvent` 的变换链与锚点（脚底中心）：
 *
 * ```
 * ax = x + lw/2,  ay = y + lh
 * M = T(ax+dx, ay+dy) · R(rot) · S(sx, sy) · T(-ax, -ay) · T(x, y)
 * ```
 *
 * 以脚底为锚点的意义：呼吸时脚不动，蹦跳时整个人离地，压扁时从脚底往上缩，
 * 角色不会在窗口里乱飘。Android 的 `postConcat` 语义是 `M' = other · M`，
 * 所以按"从内到外"的顺序 post。
 *
 * 手势有两条容易踩的坑，都在这里处理掉了：
 *
 * 1. **拖动必须读 `rawX/rawY`。** 窗口是跟着手指走的，用 `getX()` 会得到
 *    "手指在窗口内不动"的假象 —— delta 恒为 0，窗口纹丝不动。
 * 2. **单击要压后 180ms 再执行。** 桌面版的 Qt 是"单击立刻响应、双击再覆盖"，
 *    照搬过来双击会先触发一次随机动作（可能切到 whale 那种大帧），
 *    紧接着又切 happy —— 悬浮窗尺寸连改两次，肉眼能看到抖。
 *    压后一拍，双击时直接把待发的那次单击撤掉，既快又干净。
 */
class PetView(ctx: Context, private val pack: Pack) : View(ctx) {

    private val paint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
    private val m = Matrix()
    private val handler = Handler(Looper.getMainLooper())

    // ------------------------------------------------------------ 状态

    /** 当前要画的帧名。窗口尺寸由 Service 按它算出并 updateViewLayout。 */
    var frameName: String = ""
        set(v) {
            if (v != field) {
                field = v
                invalidate()
            }
        }

    /** 进入当前状态的时长（秒），动效相位 */
    var localT: Double = 0.0
        set(v) {
            field = v
            invalidate()
        }

    var opacity: Float = 1f
        set(v) {
            field = v.coerceIn(0f, 1f)
            invalidate()
        }

    // ------------------------------------------------------------ 手势回调

    var onTap: (() -> Unit)? = null
    var onDoubleTap: (() -> Unit)? = null
    var onLongPress: (() -> Unit)? = null
    var onDragStart: (() -> Unit)? = null

    /**
     * 手指落在宠物上 / 离开（含被系统 CANCEL）。
     *
     * 宿主（[OverlayService]）用它把"换帧 = 换窗口尺寸"这件事推迟到抬手之后 ——
     * 手势中途改窗口几何，有的 ROM 会把手势直接判成 CANCEL，表现就是点不灵、拖一半断掉。
     */
    var onPressChanged: ((Boolean) -> Unit)? = null

    /** 相对上一次的位移（屏幕像素），Service 拿去移动窗口 */
    var onDrag: ((Float, Float) -> Unit)? = null
    var onDragEnd: (() -> Unit)? = null

    // ------------------------------------------------------------ 手势状态

    private var downRawX = 0f
    private var downRawY = 0f
    private var lastRawX = 0f
    private var lastRawY = 0f
    private var dragging = false
    private var longFired = false
    private var lastTapNs = 0L

    /** 已经通知过宿主"按下"了，避免 UP/CANCEL 重复回调 */
    private var pressedFlag = false

    private val slop: Int by lazy { ViewConfiguration.get(context).scaledTouchSlop }
    private val longPressMs: Long by lazy {
        ViewConfiguration.getLongPressTimeout().toLong()
    }

    private val longPressRunnable = Runnable {
        if (!dragging) {
            longFired = true
            onLongPress?.invoke()
        }
    }

    /** 待发的单击。第二次点按到来时撤掉它，改发双击。 */
    private val pendingTapRunnable = Runnable {
        lastTapNs = System.nanoTime()
        onTap?.invoke()
    }

    init {
        isClickable = true
        isFocusable = false
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downRawX = e.rawX
                downRawY = e.rawY
                lastRawX = downRawX
                lastRawY = downRawY
                dragging = false
                longFired = false
                pressedFlag = true
                onPressChanged?.invoke(true)
                handler.postDelayed(longPressRunnable, longPressMs)
                return true
            }

            MotionEvent.ACTION_MOVE -> {
                if (!dragging) {
                    if (abs(e.rawX - downRawX) > slop || abs(e.rawY - downRawY) > slop) {
                        dragging = true
                        handler.removeCallbacks(longPressRunnable)
                        // 拖起来就不算单击了，把待发的那次撤掉
                        handler.removeCallbacks(pendingTapRunnable)
                        onDragStart?.invoke()
                    }
                }
                if (dragging) {
                    val dx = e.rawX - lastRawX
                    val dy = e.rawY - lastRawY
                    lastRawX = e.rawX
                    lastRawY = e.rawY
                    onDrag?.invoke(dx, dy)
                }
                return true
            }

            MotionEvent.ACTION_UP -> {
                handler.removeCallbacks(longPressRunnable)
                finishPress()
                if (longFired) {
                    handler.removeCallbacks(pendingTapRunnable)
                    return true
                }
                if (dragging) {
                    onDragEnd?.invoke()
                    return true
                }
                // 双击判定：距上一次点按够近就升级成双击
                val now = System.nanoTime()
                if (now - lastTapNs < DOUBLE_TAP_NS) {
                    handler.removeCallbacks(pendingTapRunnable)
                    lastTapNs = 0L
                    onDoubleTap?.invoke()
                } else {
                    handler.removeCallbacks(pendingTapRunnable)
                    handler.postDelayed(pendingTapRunnable, TAP_DELAY_MS)
                }
                return true
            }

            MotionEvent.ACTION_CANCEL -> {
                handler.removeCallbacks(longPressRunnable)
                finishPress()
                if (dragging) onDragEnd?.invoke()
                dragging = false
                return true
            }
        }
        return super.onTouchEvent(e)
    }

    /** 通知宿主"手指走了"，并且只通知一次。 */
    private fun finishPress() {
        if (!pressedFlag) return
        pressedFlag = false
        onPressChanged?.invoke(false)
    }

    override fun onDetachedFromWindow() {
        handler.removeCallbacksAndMessages(null)
        super.onDetachedFromWindow()
    }

    // ------------------------------------------------------------ 绘制

    override fun onDraw(canvas: Canvas) {
        // 悬浮窗是 TRANSLUCENT 的，必须显式清成透明 ——
        // 否则上一帧的像素会残留成拖影（窗口尺寸还会变，残留更明显）
        canvas.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR)

        val name = frameName
        val bmp = pack.bitmap(name) ?: return
        val sz = pack.size(name) ?: return
        val lw = sz[0].toFloat()
        val lh = sz[1].toFloat()

        // 帧永远画在窗口的 (pad, pad) 处。窗口尺寸 = 帧尺寸 + 2·pad，
        // 所以只要窗口跟着帧尺寸走，宠物在屏幕上的位置就恒定不动。
        val x = pack.pad.toFloat()
        val y = pack.pad.toFloat()

        val p = pack.motion.params(name, localT, scaleFor(lh.toDouble()))
        val dx = p[0].toFloat()
        val dy = p[1].toFloat()
        val sx = p[2].toFloat()
        val sy = p[3].toFloat()
        val rot = p[4].toFloat()

        val ax = x + lw / 2f
        val ay = y + lh

        m.reset()
        m.postTranslate(x, y)                                   // 最内层
        m.postTranslate(-ax, -ay)
        m.postScale(sx, sy)
        if (rot != 0f) m.postRotate(rot)
        m.postTranslate(ax + dx, ay + dy)                        // 最外层

        paint.alpha = (opacity * 255f).toInt().coerceIn(0, 255)
        canvas.drawBitmap(bmp, m, paint)
    }

    companion object {
        private const val TAP_DELAY_MS = 180L
        private const val DOUBLE_TAP_NS = 320_000_000L
    }
}
