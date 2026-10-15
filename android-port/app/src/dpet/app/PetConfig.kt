package dpet.app

import android.content.Context
import android.content.SharedPreferences

/**
 * 桌宠配置。
 *
 * 与桌面版 `config.json` 一一对应，只多了手机端特有的三项：
 * [pinPos]（锁定位置 = 拖不动）、[passthrough]（触摸穿透 = 完全不接收触摸）
 * 与 [idleAction]（待机是否自己演小动作，手机上更费电，得让用户能关）。
 *
 * 存 SharedPreferences。主界面与悬浮服务同进程，写入后由 [OverlayService] 收到
 * 配置变更广播再重新读取 —— **不要指望服务里缓存的副本自动跟着变**。
 */
class PetConfig(ctx: Context) {

    private val sp: SharedPreferences =
        ctx.applicationContext.getSharedPreferences("pet_config", Context.MODE_PRIVATE)

    // ------------------------------------------------------------ 开关

    /** 桌宠是否正在运行（悬浮窗是否应存在）。进程被杀后重启时用它恢复。 */
    var enabled: Boolean
        get() = sp.getBoolean("enabled", false)
        set(v) {
            sp.edit().putBoolean("enabled", v).apply()
        }

    // ------------------------------------------------------------ 外观

    /** 角色高度（dp）。桌面版是 280，但手机屏幕逻辑宽度只有 390dp 左右，得小一档。 */
    var sizeDp: Int
        get() = sp.getInt("size_dp", DEFAULT_DP).coerceIn(MIN_DP, MAX_DP)
        set(v) {
            sp.edit().putInt("size_dp", v.coerceIn(MIN_DP, MAX_DP)).apply()
        }

    var opacity: Float
        get() = sp.getFloat("opacity", 1f).coerceIn(MIN_OP, 1f)
        set(v) {
            sp.edit().putFloat("opacity", v.coerceIn(MIN_OP, 1f)).apply()
        }

    // ------------------------------------------------------------ 行为

    var bubble: Boolean
        get() = sp.getBoolean("bubble", true)
        set(v) {
            sp.edit().putBoolean("bubble", v).apply()
        }

    var sfx: Boolean
        get() = sp.getBoolean("sfx", true)
        set(v) {
            sp.edit().putBoolean("sfx", v).apply()
        }

    var sfxVolume: Float
        get() = sp.getFloat("sfx_volume", 0.6f).coerceIn(0f, 1f)
        set(v) {
            sp.edit().putFloat("sfx_volume", v.coerceIn(0f, 1f)).apply()
        }

    /** 待机时是否允许自己演小动作（happy / whale / blindfold 等按权重抽签）。 */
    var idleAction: Boolean
        get() = sp.getBoolean("idle_action", true)
        set(v) {
            sp.edit().putBoolean("idle_action", v).apply()
        }

    /** 待机眨眼。关掉可以少一次换帧（换帧要重算窗口尺寸）。 */
    var blink: Boolean
        get() = sp.getBoolean("blink", true)
        set(v) {
            sp.edit().putBoolean("blink", v).apply()
        }

    /**
     * **锁定位置**：拖不动它。
     *
     * 只掐掉"拖动"这一条路径 —— 单击、双击、长按照常响应，位置仍然可以在控制面板里
     * 用滑块/预设改。和 [passthrough] 不是一回事：那个是整个窗口不接收触摸。
     *
     * 早先这两件事被合并成一个开关，后果是"想固定位置"的人打开它之后，
     * 连点它一下都不理人，面板里又没有任何改位置的地方 —— 宠物变成了纯贴图。
     */
    var pinPos: Boolean
        get() = sp.getBoolean("pin_pos", false)
        set(v) {
            sp.edit().putBoolean("pin_pos", v).apply()
        }

    /**
     * **触摸穿透**：窗口整体 `FLAG_NOT_TOUCHABLE`，手指划过宠物**直接落到下层 app**。
     * 代价是它不再接受任何互动（点击、长按、拖动全都收不到）—— 纯观赏模式。
     *
     * 这是 Android 悬浮窗的硬限制：系统不存在"把落在透明像素上的触摸转发给下层窗口"
     * 的机制（桌面版靠 QRegion mask 做到的事，这里做不到），只能在
     * 「可互动但挡一块矩形触摸」和「完全不挡但完全不理人」之间二选一。
     */
    var passthrough: Boolean
        get() = sp.getBoolean("locked", false)      // 键名沿用 locked，老装机升级不丢设置
        set(v) {
            sp.edit().putBoolean("locked", v).apply()
        }

    // ------------------------------------------------------------ 位置

    /**
     * 宠物**脚底中心**在屏幕上的坐标（物理像素）。
     *
     * 存的是脚底锚点而不是窗口左上角：窗口尺寸会随当前帧变（idle 347px 宽、whale 516px 宽），
     * 只有锚点这个量在换帧时才是不变的。NaN 表示从没设过，用默认落点。
     */
    var posX: Float
        get() = sp.getFloat("pos_x", Float.NaN)
        set(v) {
            sp.edit().putFloat("pos_x", v).apply()
        }

    var posY: Float
        get() = sp.getFloat("pos_y", Float.NaN)
        set(v) {
            sp.edit().putFloat("pos_y", v).apply()
        }

    fun savePos(x: Float, y: Float) {
        sp.edit().putFloat("pos_x", x).putFloat("pos_y", y).apply()
    }

    fun hasPos(): Boolean = !posX.isNaN() && !posY.isNaN()

    companion object {
        const val MIN_DP = 80
        const val MAX_DP = 320
        const val DEFAULT_DP = 170
        const val MIN_OP = 0.35f

        /**
         * 默认落点：屏幕宽/高的比例 —— 脚底中心落在右下角。
         *
         * 数值是**避开系统手势热区**算出来的，不是随手写的：Android 从左右边缘向内约
         * 20dp 是"返回手势"的起手区，手指从那里起划会被系统抢走 —— 表现就是"它拖不动"。
         * idle 帧宽 347px，锚点在 0.76·1080 = 821 时宠物右缘距屏幕边缘约 85px，
         * 稳稳在热区之外（实测 1080 宽的机器上 edge slop 约 44px）。别往 0.85 以上推。
         */
        const val DEFAULT_X_FRAC = 0.76f
        const val DEFAULT_Y_FRAC = 0.86f
    }
}
