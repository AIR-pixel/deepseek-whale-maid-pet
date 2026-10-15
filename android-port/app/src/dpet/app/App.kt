package dpet.app

/** 应用级常量。放在一处，免得版本号在几个文件里各写一遍。 */
object App {
    const val VERSION = "2.0.0"
    const val NAME = "DeepSeek 鲸鱼娘"
}

/**
 * 控制面板是否在前台。
 *
 * 为什么用同进程静态对象而不是广播：广播有个**时序坑**。Activity 与 Service
 * 虽然在同一个进程里，但服务可能是被 `onResume` 里那句 ensureService 刚拉起来的 ——
 * 那一刻它的接收器还没注册，这条广播就丢了。结果是面板上拖滑块时宠物仍然在吃触摸
 * （实测：滑块纹丝不动，宠物窗口反而换了个帧尺寸）。
 *
 * 直接共享一个变量没有这个问题：服务起来时主动读一次当前值，
 * 服务被系统回收后重建也能立刻拿到正确状态。
 */
object PanelState {

    @Volatile
    var open: Boolean = false
        private set

    private var listener: ((Boolean) -> Unit)? = null

    fun set(v: Boolean) {
        open = v
        listener?.invoke(v)
    }

    /** 服务注册监听。注册时立刻回调一次当前值，状态不会漂。 */
    fun observe(l: (Boolean) -> Unit) {
        listener = l
        l(open)
    }

    fun clear() {
        listener = null
    }
}
