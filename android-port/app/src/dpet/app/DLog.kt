package dpet.app

import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 落盘日志。
 *
 * 为什么不用 logcat：这台 Redmi Note 11（Android 17 / HyperOS）上
 * `adb shell logcat` 直接报 `logd not running` / `failed to get the readable
 * 'main,system,crash,kernel' log sizes` —— 系统不给 shell 读 log buffer，
 * 整个调试过程拿不到一行日志。所以关键事件同时写进
 * `Android/data/dpet.app/files/dpet.log`，那个目录 adb 可以直接 pull，
 * 不需要 root、也不需要给正式包开 `debuggable`。
 *
 * 顺带把未捕获异常也接上 —— 没有崩溃日志的调试是盲人摸象。
 */
object DLog {

    private const val TAG = "PETAPP"
    private const val MAX_BYTES = 256L * 1024

    private var file: File? = null
    private var crashInstalled = false
    private val fmt = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US)
    private val lock = Any()

    fun init(ctx: Context) {
        if (file == null) {
            val dir = ctx.getExternalFilesDir(null) ?: ctx.filesDir
            val f = File(dir, "dpet.log")
            try {
                if (f.length() > MAX_BYTES) {
                    val keep = f.readText(Charsets.UTF_8).takeLast((MAX_BYTES / 2).toInt())
                    f.writeText("--- 已截断 ---\n$keep", Charsets.UTF_8)
                }
            } catch (_: Throwable) {
            }
            file = f
        }
        installCrashHandler()
        i("=== 会话开始 v${App.VERSION} ===")
    }

    fun i(msg: String) {
        Log.i(TAG, msg)
        append("I", msg)
    }

    fun w(msg: String, t: Throwable? = null) {
        Log.w(TAG, msg, t)
        append("W", msg + suffix(t))
    }

    fun e(msg: String, t: Throwable? = null) {
        Log.e(TAG, msg, t)
        append("E", msg + suffix(t))
    }

    /** 日志文件路径，取不到就返回空串 */
    fun path(ctx: Context): String =
        (file ?: File(ctx.getExternalFilesDir(null) ?: ctx.filesDir, "dpet.log")).absolutePath

    private fun suffix(t: Throwable?): String =
        if (t == null) "" else "\n    ${t}\n" + t.stackTraceToString().lineSequence()
            .take(24).joinToString("\n") { "    $it" }

    private fun append(level: String, msg: String) {
        val f = file ?: return
        try {
            synchronized(lock) {
                FileWriter(f, true).use { it.write("[${fmt.format(Date())}] $level $msg\n") }
            }
        } catch (_: Throwable) {
        }
    }

    private fun installCrashHandler() {
        if (crashInstalled) return
        crashInstalled = true
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            e("未捕获异常 @${t.name}", e)
            prev?.uncaughtException(t, e)
        }
    }
}
