package dpet.app

import android.content.Context
import android.content.SharedPreferences

/**
 * 桌宠配置。
 *
 * 与桌面版 `config.json` 一一对应，只多了手机端特有的两项：
 * [locked]（锁定位置 = 悬浮窗整窗触摸穿透，只剩观赏）与
 * [idleAction]（待机是否自己演小动作，手机上更费电，得让用户能关）。
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
     * 锁定位置：窗口整体 `FLAG_NOT_TOUCHABLE`，手指划过宠物**直接落到下层 app**。
     * 代价是不能再拖动它 —— 需要移动时回来关掉这项。
     *
     * 这是 Android 悬浮窗的硬限制：系统不存在"把落在透明像素上的触摸转发给下层窗口"
     * 的机制（桌面版靠 QRegion mask 做到的事，这里做不到），只能在
     * 「可拖动但挡一块矩形触摸」和「完全不挡但动不了」之间二选一。
     */
    var locked: Boolean
        get() = sp.getBoolean("locked", false)
        set(v) {
            sp.edit().putBoolean("locked", v).apply()
        }

    // ------------------------------------------------------------ 位置

    /** 悬浮窗左上角（物理像素）。NaN 表示从没被拖动过，用默认落点。 */
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
    }
}
