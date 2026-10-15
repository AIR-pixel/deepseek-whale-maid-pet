package dpet.core

import java.io.File

/**
 * 最小 JSON 解析器 —— 只覆盖 actions.json 用到的那一子集。
 *
 * 为什么不用现成库
 * ----------------
 * 这个模块要原样搬进 Android 工程。Android 有内置的 org.json，但它是
 * Android SDK 的一部分、在纯 JVM 上跑不了；而这个解析器**没有任何依赖**，
 * 于是同一份代码既能在桌面上跑回归验证，也能在 Android 上跑。
 *
 * 设计取舍
 * --------
 * * 数字一律解析成 Double。actions.json 里所有数值（周期、幅度、权重）
 *   本来就是浮点，Python 侧 motion.py 也处处 float(...) 转换，不存在整数语义。
 * * 对象用 LinkedHashMap 保留插入顺序 —— 与 Python dict 行为一致，
 *   排查差异时不会因为遍历顺序不同造成假象。
 * * 逃逸序列完整处理，因为动作名和台词里会出现中文（\uXXXX 形式）。
 */
object MiniJson {

    fun parseFile(path: String): Any? = parse(File(path).readText(Charsets.UTF_8))

    fun parse(text: String): Any? {
        val p = Parser(text)
        p.skipWs()
        val v = p.parseValue()
        p.skipWs()
        require(p.pos == text.length) { "JSON 尾部有多余内容 @${p.pos}" }
        return v
    }

    private class Parser(private val s: String) {
        var pos = 0

        fun skipWs() {
            while (pos < s.length) {
                val c = s[pos]
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') pos++ else break
            }
        }

        fun parseValue(): Any? {
            skipWs()
            if (pos >= s.length) throw IllegalArgumentException("JSON 意外结束")
            val c = s[pos]
            return when {
                c == '{' -> parseObject()
                c == '[' -> parseArray()
                c == '"' -> parseString()
                c == 't' -> { expect("true"); true }
                c == 'f' -> { expect("false"); false }
                c == 'n' -> { expect("null"); null }
                c == '-' || c.isDigit() -> parseNumber()
                else -> throw IllegalArgumentException("非法字符 '$c' @$pos")
            }
        }

        private fun expect(word: String) {
            if (!s.startsWith(word, pos)) throw IllegalArgumentException("期望 $word @$pos")
            pos += word.length
        }

        private fun parseObject(): LinkedHashMap<String, Any?> {
            val out = LinkedHashMap<String, Any?>()
            pos++
            skipWs()
            if (pos < s.length && s[pos] == '}') { pos++; return out }
            while (true) {
                skipWs()
                val key = parseString()
                skipWs()
                if (pos >= s.length || s[pos] != ':') {
                    throw IllegalArgumentException("期望 ':' @$pos")
                }
                pos++
                out[key] = parseValue()
                skipWs()
                if (pos >= s.length) throw IllegalArgumentException("对象未闭合")
                when (s[pos]) {
                    ',' -> pos++
                    '}' -> { pos++; return out }
                    else -> throw IllegalArgumentException("期望 ',' 或 '}' @$pos")
                }
            }
        }

        private fun parseArray(): ArrayList<Any?> {
            val out = ArrayList<Any?>()
            pos++
            skipWs()
            if (pos < s.length && s[pos] == ']') { pos++; return out }
            while (true) {
                out.add(parseValue())
                skipWs()
                if (pos >= s.length) throw IllegalArgumentException("数组未闭合")
                when (s[pos]) {
                    ',' -> pos++
                    ']' -> { pos++; return out }
                    else -> throw IllegalArgumentException("期望 ',' 或 ']' @$pos")
                }
            }
        }

        private fun parseString(): String {
            if (pos >= s.length || s[pos] != '"') {
                throw IllegalArgumentException("期望字符串 @$pos")
            }
            pos++
            val sb = StringBuilder()
            while (true) {
                if (pos >= s.length) throw IllegalArgumentException("字符串未闭合")
                val c = s[pos++]
                if (c == '"') return sb.toString()
                if (c != '\\') { sb.append(c); continue }
                if (pos >= s.length) throw IllegalArgumentException("转义未完成")
                when (val e = s[pos++]) {
                    '"' -> sb.append('"')
                    '\\' -> sb.append('\\')
                    '/' -> sb.append('/')
                    'b' -> sb.append('\b')
                    'f' -> sb.append('\u000C')
                    'n' -> sb.append('\n')
                    'r' -> sb.append('\r')
                    't' -> sb.append('\t')
                    'u' -> {
                        if (pos + 4 > s.length) {
                            throw IllegalArgumentException("\\u 转义不完整 @$pos")
                        }
                        val hex = s.substring(pos, pos + 4)
                        pos += 4
                        sb.append(hex.toInt(16).toChar())
                    }
                    else -> throw IllegalArgumentException("未知转义 \\$e")
                }
            }
        }

        private fun parseNumber(): Double {
            val start = pos
            if (pos < s.length && s[pos] == '-') pos++
            while (pos < s.length && s[pos].isDigit()) pos++
            if (pos < s.length && s[pos] == '.') {
                pos++
                while (pos < s.length && s[pos].isDigit()) pos++
            }
            if (pos < s.length && (s[pos] == 'e' || s[pos] == 'E')) {
                pos++
                if (pos < s.length && (s[pos] == '+' || s[pos] == '-')) pos++
                while (pos < s.length && s[pos].isDigit()) pos++
            }
            return s.substring(start, pos).toDouble()
        }
    }
}
