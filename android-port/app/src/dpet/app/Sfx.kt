package dpet.app

import android.content.Context
import android.media.AudioAttributes
import android.media.SoundPool
import java.io.File

/**
 * 交互音效。
 *
 * 与桌面版 `src/sfx.py` 对齐的三条纪律：
 *
 * 1. **不能"第一次点没声音"**：SoundPool 是异步解码的，[SoundPool.load] 返回的
 *    soundId 在解码完成前 `play()` 无效。所以维护一个 [ready] 集合，
 *    只有解码完的 cue 才允许播（加载完成回调里补进去）。
 * 2. **不同 cue 几乎同时触发会叠成怪音**：点击常常既触发状态音又触发气泡音，
 *    用一个全局最小间隔挡掉后到的那个。同一个 cue 连打由 SoundPool 自己合并。
 * 3. **任何失败都静默降级**：没声音可以接受，桌宠崩掉不行。
 */
class Sfx {

    private var pool: SoundPool? = null
    private val idByName = HashMap<String, Int>()
    private val ready = HashSet<Int>()

    var enabled = true
    var volume = 0.6f
        set(v) {
            field = v.coerceIn(0f, 1f)
            pool?.let { p -> for (id in idByName.values) p.setVolume(id, field, field) }
        }

    private var lastNs = 0L

    /** 有几个 cue 真的可用了（给启动日志/自检看） */
    val readyCount: Int get() = ready.size

    val totalCount: Int get() = idByName.size

    fun load(ctx: Context) {
        if (pool != null) return
        val p = SoundPool.Builder()
            .setMaxStreams(4)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            .build()

        p.setOnLoadCompleteListener { _, sampleId, status ->
            if (status == 0) ready.add(sampleId)
        }
        pool = p

        // 动态扫 assets/sfx —— 远端内容包将来加了新音效也能自动认出来
        val names = try {
            ctx.assets.list("sfx")?.mapNotNull {
                if (it.endsWith(".wav")) it.substringBeforeLast(".wav") else null
            } ?: emptyList()
        } catch (_: Throwable) {
            emptyList()
        }

        // 先把 wav 落到内部存储，再交给 `SoundPool.load(String)`。
        //
        // 为什么不直接用 assets：`load(InputStream)` 这个重载**根本不存在**，
        // 而 `load(AssetFileDescriptor)` 要求 assets 里的文件是"未压缩存储"的 ——
        // 那取决于 aapt2 有没有压它，不该让运行时代码去赌一个打包选项。
        // 落到 filesDir 之后是一条确定的路径，且不像 cacheDir 那样会被系统清掉。
        val dir = File(ctx.filesDir, "sfx").apply { mkdirs() }
        for (name in names) {
            try {
                val f = File(dir, "$name.wav")
                if (!f.exists() || f.length() == 0L) {
                    ctx.assets.open("sfx/$name.wav").use { ins ->
                        f.outputStream().use { out -> ins.copyTo(out) }
                    }
                }
                val id = p.load(f.absolutePath, 1)
                if (id != 0) {
                    idByName[name] = id
                    p.setVolume(id, volume, volume)
                }
            } catch (_: Throwable) {
                // 单个音效读不出来就跳过
            }
        }
        DLog.i("音效预载 %d 条: %s".format(idByName.size, idByName.keys.sorted()))
    }

    /**
     * 播放一个 cue。cue 名写错、还没解码完、或距上一条不足 110ms —— 都静默返回 false。
     * 返回布尔值是为了让调用方（和测试）能断言"这次到底出声没有"。
     */
    fun play(name: String): Boolean {
        if (!enabled || volume <= 0f) return false
        val p = pool ?: return false
        val id = idByName[name] ?: return false
        if (id !in ready) return false

        val now = System.nanoTime()
        if (now - lastNs < GATE_NS) return false
        lastNs = now
        p.play(id, volume, volume, 1, 0, 1f)
        DLog.i("音效: $name")
        return true
    }

    fun release() {
        pool?.release()
        pool = null
        idByName.clear()
        ready.clear()
    }

    companion object {

        /** 不同 cue 之间的最小间隔 */
        private const val GATE_NS = 110_000_000L
    }
}
