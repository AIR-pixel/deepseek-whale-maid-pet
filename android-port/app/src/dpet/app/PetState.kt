package dpet.app

import kotlin.random.Random

/**
 * 状态机 —— 桌面版 `PetWindow._tick` 的手机端对应物。
 *
 * 与桌面版的两处**有意不同**：
 *
 * 1. **空闲判定换了信号源。** 桌面版读 `GetLastInputInfo`（系统级无输入时长）。
 *    Android 上普通应用拿不到这个量 —— 没有 `INJECT_EVENTS` / 无障碍服务就别想
 *    知道"用户刚才在别的 app 里点了什么"。所以改成两个能拿到的信号：
 *    **屏幕是否亮** + **宠物自己多久没被摸过**。这其实更贴合手机场景：
 *    屏幕灭掉就是"主人不在了"，直接睡；亮着但一直不搭理（在看视频/读文章）
 *    才是犯困。桌面版那套 3 分钟犯困在手机上太急了，这里放宽到 5 分钟。
 *
 * 2. **自发小动作的概率按 dt 算，不按 tick 计数。** 桌面版写死"每 tick 0.0016"，
 *    帧率一改含义就变了；这里写成 `dt / 平均间隔秒数`，30fps 和 25fps 得到的
 *    平均间隔完全一致。
 */
class PetState(private val pack: Pack) {

    companion object {
        /** 主循环步长。与 Service 的目标帧率绑定。 */
        const val TICK_DT = 1.0 / 30.0

        /** 待机时平均多久自发演一个小动作（秒） */
        private const val MEAN_IDLE_SEC = 25.0

        /** 工作状态平均多久自己歇一下（秒） */
        private const val MEAN_WORK_EXIT_SEC = 33.0

        /** 亮屏后多久没被搭理就犯困（秒）。桌面版是 180，手机调到 300。 */
        private const val DOZE_AFTER_SEC = 300.0

        /** 屏幕一亮就醒来，但要"确实被冷落过"才值得说一句 —— 短于这个不吭声 */
        private const val WAKE_MIN_SEC = 3.0

        private val STATE_CUE = mapOf(
            "happy" to "happy",
            "blindfold" to "shy",
            "whale" to "whale",
            "eat" to "eat",
            "work" to "work"
        )
    }

    var state = "idle"
        private set

    var frame = ""
        private set

    /** 全局时间（秒），动效相位基准 */
    var t = 0.0
        private set

    private var stateT0 = 0.0
    private var deadline = 0.0              // 毫秒；0 = 当前不是临时状态
    private var blinkUntil = 0.0
    private var nextBlink = 0.0

    /** 刚从"睡着"里被屏幕点亮 —— 问候补在解锁那一刻，见 [onUserPresent] */
    private var wokeFromSleep = false

    /** 这次亮屏欠着一句问候还没说（宿主在锁屏解开时调 [onUserPresent] 兑现） */
    val awaitingWakeGreeting: Boolean get() = wokeFromSleep

    private var idlePool: List<Pair<String, Int>> = pack.idlePool()
    private val blinkFrames: Pair<String, String>? = pack.blinkFrames()

    /** 进入当前状态后经过的时间 —— 动效曲线用它当相位，切状态即归零 */
    val localT: Double get() = t - stateT0

    /** `(台词, cue)`。cue 为 null 表示这次不出声（调用方已经播过更贴切的音了）。 */
    var onSay: ((String, String?) -> Unit)? = null

    fun say(text: String, cue: String? = null) = onSay?.invoke(text, cue)

    /** 内容热加载后重算池子（当前手机版没有远端内容，但留着这个口子） */
    fun refreshPools() {
        idlePool = pack.idlePool()
    }

    fun start(greeting: Boolean) {
        state = "idle"
        stateT0 = 0.0
        deadline = 0.0
        frame = pack.firstFrame()
        nextBlink = t + 2.5 + Random.nextDouble() * 3.5
        if (greeting) {
            val meta = pack.stateMeta("idle")
            val pool = meta?.lines?.takeIf { it.isNotEmpty() } ?: Lines.greetNow()
            onSay?.invoke(Lines.pick(pool), "hello")
        }
    }

    /**
     * 切状态。
     *
     * [cue] 三态：null = 用内容包/内置表的默认音；`""` = 强制不出声；
     * 其它字符串 = 用指定的 cue。用 `""` 而不是再开一个布尔参数，
     * 是因为调用点几乎都是"这次交互已经播了更贴切的音，画面照切但别响"。
     */
    fun setState(name: String, force: Boolean = false, cue: String? = null) {
        if (name == state && !force) return
        val meta = pack.stateMeta(name) ?: return

        val prev = state
        state = name
        stateT0 = t
        frame = meta.frames[Random.nextInt(meta.frames.size)]
        deadline = if (meta.temp && meta.durMax > 0) {
            t * 1000.0 + meta.durMin + Random.nextDouble() * (meta.durMax - meta.durMin)
        } else {
            0.0
        }

        val want = cue ?: meta.cue ?: STATE_CUE[name]
        if (!want.isNullOrEmpty()) onSay?.invoke("", want)
        DLog.i("状态: $prev -> $name")
    }

    /**
     * 驱动一帧。
     *
     * [idleSec] = 距离上一次"用户搭理它"（摸宠物 / 屏幕亮起）过去了多少秒。
     */
    fun tick(dt: Double, idleSec: Double, cfg: PetConfig) {
        t += dt

        // 1) 临时状态到期 -> 回 idle
        if (deadline > 0 && t * 1000.0 >= deadline) setState("idle", force = true)

        // 2) 空闲分层：亮着但没人理 -> 犯困；再被搭理 -> 醒
        if (state == "idle" || state == "work") {
            if (idleSec > DOZE_AFTER_SEC) setState("doze", cue = "")
        } else if (state == "doze" || state == "sleep") {
            if (idleSec < WAKE_MIN_SEC) {
                setState("idle", force = true, cue = "")
                onSay?.invoke(Lines.pick(Lines.WAKE), "wake")
            }
        }

        // 3) 自发小动作。AUTO_CUE 对应"自发不出声"——
        //    每隔几十秒自己响一声会变成噪音，交互反馈音才是需求。
        if (state == "idle" && cfg.idleAction && Random.nextDouble() < dt / MEAN_IDLE_SEC) {
            setState(pickIdle(), cue = "")
        } else if (state == "work" && Random.nextDouble() < dt / MEAN_WORK_EXIT_SEC) {
            setState("idle", force = true, cue = "")
        }

        // 4) 眨眼：只在 idle 且确实有这两帧时做
        if (state == "idle" && cfg.blink) {
            val bf = blinkFrames ?: return
            if (t < blinkUntil) {
                if (frame != bf.second) frame = bf.second
            } else {
                if (frame == bf.second) frame = bf.first
                if (t >= nextBlink) {
                    nextBlink = t + 2.4 + Random.nextDouble() * 4.6
                    blinkUntil = t + 0.12
                    frame = bf.second
                }
            }
        }

        // 5) 单帧状态（非 idle）没有眨眼这回事，保证帧和状态对得上
        if (state != "idle") {
            val meta = pack.stateMeta(state) ?: return
            if (frame !in meta.frames) frame = meta.frames[Random.nextInt(meta.frames.size)]
        }
    }

    /** 屏幕灭 —— 由 Service 的广播接收器驱动 */
    fun onScreenOff() {
        // 屏幕都黑了，说给谁听。安静地睡。
        wokeFromSleep = false
        setState("sleep", force = true, cue = "")
    }

    /**
     * 屏幕亮。
     *
     * 这里**只把画面叫醒，不吭声**：亮屏常常只是用户瞄一眼锁屏上的时间，
     * 而且锁屏界面上气泡根本看不见（keyguard 在 overlay 之上）。
     * "该补一句问候"这件事记在 [wokeFromSleep] 上，交给 [onUserPresent]。
     *
     * 早先这里直接把状态改成 idle，结果 [onUserPresent] 的前置条件再也
     * 不成立，解锁问候**永远说不出口** —— 别退回去。
     */
    fun onScreenOn() {
        if (state == "sleep" || state == "doze") {
            setState("idle", force = true, cue = "")
            wokeFromSleep = true
        }
    }

    /**
     * 解锁完成（`ACTION_USER_PRESENT`）。这才是"人回来了"的时刻。
     *
     * 正常路径：灭屏 -> sleep，亮屏 -> 醒着但不出声（[onScreenOn] 置位），
     * 解锁 -> 在这里补一句。兜底分支管"设备没发 SCREEN_ON 就直接解锁"，
     * 免得该说话时一声不吭。
     */
    fun onUserPresent() {
        val fromSleep = wokeFromSleep || state == "sleep" || state == "doze"
        wokeFromSleep = false
        if (!fromSleep) return
        setState("idle", force = true, cue = "")
        onSay?.invoke(Lines.pick(Lines.WAKE), "wake")
    }

    private fun pickIdle(): String {
        if (idlePool.isEmpty()) return "idle"
        var total = 0
        for ((_, w) in idlePool) total += w
        if (total <= 0) return "idle"
        var r = Random.nextInt(total)
        for ((n, w) in idlePool) {
            r -= w
            if (r < 0) return n
        }
        return idlePool.last().first
    }
}
