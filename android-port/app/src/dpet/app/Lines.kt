package dpet.app

import java.util.Calendar

/**
 * 鲸鱼娘台词库 —— `src/lines.py` 的手机端副本。
 *
 * 人设：聪明但懒、傲娇、嘴硬心软、理直气壮地待机偷懒，标志性道具是一碗白饭。
 *
 * 为什么不做成 assets 里的 JSON：它是**文案**不是**内容包**。内容包（actions.json）
 * 承载的是"远端可以下发新动作"这件事，要能热更新、要过 SHA 自检；
 * 台词改动跟着版本走就够了，塞进 assets 只会让内容包自检多一个易错点。
 */
object Lines {

    val GREET_DAWN = listOf(
        "天还没亮……你也没睡？",
        "这个点还醒着，你比我还拼。",
        "凌晨的白饭最香，我说真的。"
    )
    val GREET_MORNING = listOf(
        "早。今天也记得投喂我。",
        "哈啊……才几点，饭呢？",
        "早上好，我今天的算力已经用完了。"
    )
    val GREET_NOON = listOf(
        "午饭时间。你吃了吗？反正我要吃。",
        "这个点了，不打算管我饭？",
        "中午了，我建议你现在就去吃饭，顺便带上我的。"
    )
    val GREET_AFTERNOON = listOf(
        "下午茶……哦，我只有白饭。",
        "别看我，我在认真思考（并没有）。",
        "这个点容易困，不是我的问题，是生物钟。"
    )
    val GREET_EVENING = listOf(
        "晚上好。今天的数据挺乖的，我心情不错。",
        "晚饭吃了吗？我可以帮你尝一口。",
        "一天快过去了，你还没喂我。"
    )
    val GREET_NIGHT = listOf(
        "这个点还不睡？那我先犯困了。",
        "夜深了，我要进入 DeepSleep 了。",
        "又在熬夜。行吧，我陪你。"
    )

    /** 单击 */
    val POKE = listOf(
        "戳我干什么，我又不是按钮。",
        "……再戳一下我就真的动了。",
        "哼，看你这么有诚意，就理你一下。",
        "你这是摸头吗？手法一般。",
        "想吃白饭。重要的事说三遍：白饭、白饭、白饭。",
        "别急，我在想事情。想的是吃什么。",
        "又戳。你是不是没别的事干了。",
        "我的注意力很贵的，你刚刚花掉了一勺。",
        "理你了。说吧，什么事。",
        "就一下。多了要加钱。",
        "嗯？我听着呢。",
        "刚刚是不是在偷看我干活。"
    )

    val DBLCLICK = listOf(
        "干嘛干嘛，手很闲？",
        "行行行，我精神点了。",
        "双击？你以为我会跳起来吗。……我跳了。",
        "这算摸头还是算骚扰。"
    )

    val DRAG = listOf(
        "放我下来。",
        "搬家吗？行吧。",
        "这个位置……勉强可以。",
        "轻点，我头发很长。",
        "别往角落里塞，我要晒太阳。"
    )

    /** 位置开关锁着，用户还在拽它 —— 得说明白为什么一动不动 */
    val PINNED = listOf(
        "位置锁着呢。要搬我去控制面板，别使劲拽。",
        "拽不动吧？我自己锁的。",
        "这个位置我决定待着，不挪了。",
        "想搬我？先把手滑到面板里把锁解开。"
    )

    val DOZE = listOf(
        "困。别叫我，我这是 DeepSleep。",
        "zzz…… 别吵，我在做压力测试。",
        "再撑一会儿……好吧撑不住了。",
        "你怎么不动了。那我也歇了。",
        "待机中。待机是我的强项。"
    )

    val SLEEP = listOf(
        "zzz……",
        "（睡着了，别再戳了）",
        "梦里全是白饭。",
        "别吵……我在跑一个很长的任务。"
    )

    val WAKE = listOf(
        "唔……谁。",
        "醒了醒了，什么事。",
        "我刚刚只是在闭目养神。",
        "（揉眼睛）到饭点了？"
    )

    val WORK = listOf(
        "正在跑，别催。",
        "这个 bug……不是我的错。",
        "我在思考，真的。",
        "别打断我，我在算一个很复杂的东西。",
        "进度 87%，剩下 13% 要花 5 倍时间。",
        "这个问题我已经有答案了，只是还没说。"
    )

    val EAT = listOf(
        "白饭！终于！",
        "干饭不积极，思想有问题。",
        "这碗我收下了，谢谢款待。",
        "吃饭的时候不要跟我说话。",
        "先吃饭，工作的事一会儿再说。"
    )

    val HAPPY = listOf(
        "嘿嘿。",
        "今天表现不错，给你个好评。",
        "算你有点良心。",
        "嗯，这个可以有。",
        "心情好，今天不偷懒了……大概。"
    )

    val SHY = listOf(
        "看不见看不见。",
        "哇，别突然放大图，我害羞。",
        "非礼勿视。",
        "挡一下。刚才那个不是我。"
    )

    val WHALE = listOf(
        "……（变成了一条鱼）",
        "这就是我的本体，蓝色大肥鱼。",
        "咕噜咕噜。",
        "变回原型了，别嫌我胖。",
        "这样比较省电。"
    )

    /** 屏幕锁了 / 用户去别的 app 了，回来时说的话 */
    val BACK = listOf(
        "你回来了。",
        "我一直在。",
        "刚刚去哪儿了？",
        "（假装没在等你）"
    )

    /** 抽一个"理你一下"的台词：优先内容包给的，没给就用状态表里的 */
    fun byState(state: String): List<String> = when (state) {
        "idle" -> POKE
        "doze" -> DOZE
        "sleep" -> SLEEP
        "work" -> WORK
        "eat" -> EAT
        "happy" -> HAPPY
        "blindfold" -> SHY
        "whale" -> WHALE
        else -> POKE
    }

    fun greetByHour(hour: Int): List<String> = when {
        hour < 6 -> GREET_DAWN
        hour < 11 -> GREET_MORNING
        hour < 14 -> GREET_NOON
        hour < 18 -> GREET_AFTERNOON
        hour < 23 -> GREET_EVENING
        else -> GREET_NIGHT
    }

    fun greetNow(): List<String> = greetByHour(Calendar.getInstance().get(Calendar.HOUR_OF_DAY))

    fun pick(pool: List<String>): String =
        if (pool.isEmpty()) "" else pool[(Math.random() * pool.size).toInt().coerceIn(0, pool.size - 1)]
}
