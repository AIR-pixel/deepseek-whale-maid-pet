package dpet.app

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView

/**
 * 极简 UI 工具箱。
 *
 * 整套界面是**纯代码构建**的 —— 不引 AndroidX、不放 res/layout、甚至不放 res/drawable。
 * 这不是洁癖，是构建链决定的：手工链（aapt2→kotlinc→d8）里没有资源编译器帮忙
 * 把 XML 编成二进制，用 XML 反而要自己处理 res 目录。几百行命令式建 View 的代码，
 * 换来的是"改一行、10 秒后装机"的迭代速度。
 *
 * 颜色就一套深色主题。桌宠本来就是深色素材 + 半透明气泡，界面跟着走更协调；
 * 做浅色主题要再铺一遍对比度，收益不值。
 */
object Ui {

    val BG = Color.rgb(17, 19, 26)
    val CARD = Color.rgb(28, 32, 42)
    val CARD_HI = Color.rgb(38, 44, 58)
    val LINE = Color.rgb(52, 59, 76)
    val TEXT = Color.rgb(232, 238, 250)
    val TEXT_DIM = Color.rgb(150, 160, 180)
    val ACCENT = Color.rgb(110, 168, 254)
    val ACCENT_DIM = Color.rgb(58, 84, 130)
    val WARN = Color.rgb(240, 180, 90)
    val DANGER = Color.rgb(232, 106, 106)
}

// ---------------------------------------------------------------- dp / sp

fun Context.dp(v: Int): Int = Math.round(v * resources.displayMetrics.density)
fun Context.dpF(v: Float): Float = v * resources.displayMetrics.density

/** sp → px。刻意**不**跟随系统字体缩放：布局是按固定比例算的，放大会挤爆。 */
fun Context.sp(v: Float): Float = TypedValue.applyDimension(
    TypedValue.COMPLEX_UNIT_SP, v, resources.displayMetrics
)

fun View.dpInt(v: Int): Int = context.dp(v)

// ---------------------------------------------------------------- 背景

fun Context.roundBg(color: Int, radiusDp: Float = 14f, strokeColor: Int? = null): GradientDrawable {
    val d = GradientDrawable()
    d.shape = GradientDrawable.RECTANGLE
    d.cornerRadius = dpF(radiusDp)
    d.setColor(color)
    if (strokeColor != null) d.setStroke(dp(1), strokeColor)
    return d
}

// ---------------------------------------------------------------- 控件工厂

fun Context.linear(
    vertical: Boolean = true,
    paddingDp: Int = 0,
    bg: Int? = null,
    radiusDp: Float = 14f
): LinearLayout = LinearLayout(this).apply {
    orientation = if (vertical) LinearLayout.VERTICAL else LinearLayout.HORIZONTAL
    if (paddingDp != 0) setPadding(dp(paddingDp), dp(paddingDp), dp(paddingDp), dp(paddingDp))
    if (bg != null) background = roundBg(bg, radiusDp)
}

fun Context.textView(
    text: String,
    sizeSp: Float = 15f,
    color: Int = Ui.TEXT,
    bold: Boolean = false
): TextView = TextView(this).apply {
    this.text = text
    textSize = sizeSp
    setTextColor(color)
    if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
    includeFontPadding = false
}

/** 一行「标题 + 说明」 */
fun Context.titleBlock(title: String, sub: String = ""): LinearLayout {
    val box = linear(vertical = true)
    box.addView(textView(title, 16f, Ui.TEXT, bold = true))
    if (sub.isNotEmpty()) {
        val s = textView(sub, 12.5f, Ui.TEXT_DIM)
        val lp = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        )
        lp.topMargin = dp(3)
        s.layoutParams = lp
        box.addView(s)
    }
    return box
}

fun Context.spacer(h: Int): View = View(this).apply {
    layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(h))
}

fun Context.hRule(): View = View(this).apply {
    layoutParams = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT, Math.max(1, dp(1))
    ).also { it.topMargin = dp(14); it.bottomMargin = dp(14) }
    setBackgroundColor(Ui.LINE)
}

fun Context.marginBottom(v: View, dpBottom: Int) {
    val lp = v.layoutParams ?: LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    )
    if (lp is LinearLayout.LayoutParams) lp.bottomMargin = dp(dpBottom)
    v.layoutParams = lp
}
