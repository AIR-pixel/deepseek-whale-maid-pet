import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

/**
 * 跨语言浮点探针：拿 Python 侧的真实调用参数，在 JVM 上复算，量出实际差异。
 *
 * 为什么需要它
 * ------------
 * motion.py 移植到 Kotlin 时，"输出一个数值都没变" 这条铁律会遇到一个物理障碍：
 * CPython 的 math.sin 走 C 运行库，JVM 的 Math.sin 走它自己的实现，
 * 两者都只承诺几 ULP 内的正确性，不保证 bit-exact。
 *
 * 所以不能假设容差，只能实测。这个探针回答两个问题：
 *   1. sin 差多少 → 换算成动效位移是多少像素
 *   2. x**3 该写成 x*x*x 还是 Math.pow(x,3.0)，哪个和 CPython 一致
 *
 * 判据：文档里说 0.0001 px 的偏差在小尺寸下就能被肉眼看见。
 * 只要实测误差远低于这个量级，就可以放心把容差定在 1e-9 而不是死磕 0。
 */
public class SinProbe {

    /** 把 double 映射成单调递增的整数，使「差值」等同于 ULP 距离（正确处理负数） */
    static long orderedBits(double d) {
        long b = Double.doubleToRawLongBits(d);
        return b < 0 ? Long.MIN_VALUE - b : b;
    }

    static long ulpDiff(double a, double b) {
        return Math.abs(orderedBits(a) - orderedBits(b));
    }

    public static void main(String[] args) throws Exception {
        String dir = args.length > 0 ? args[0] : ".";
        probeSin(Paths.get(dir, "sin_calls.tsv"));
        System.out.println();
        probeCube(Paths.get(dir, "cube_calls.tsv"));
    }

    static void probeSin(Path p) throws Exception {
        List<String> lines = Files.readAllLines(p, StandardCharsets.UTF_8);
        int n = 0, exact = 0;
        double maxAbs = 0.0, maxX = 0.0, maxPy = 0.0, maxJv = 0.0;
        long maxUlp = 0;

        for (String line : lines) {
            if (line.isEmpty()) continue;
            String[] parts = line.split("\t");
            double x = Double.parseDouble(parts[0]);
            double py = Double.parseDouble(parts[1]);
            double jv = Math.sin(x);
            n++;
            if (Double.doubleToRawLongBits(py) == Double.doubleToRawLongBits(jv)) {
                exact++;
                continue;
            }
            double d = Math.abs(py - jv);
            long u = ulpDiff(py, jv);
            if (d > maxAbs) { maxAbs = d; maxX = x; maxPy = py; maxJv = jv; }
            if (u > maxUlp) maxUlp = u;
        }

        System.out.println("== Math.sin  vs  Python math.sin ==");
        System.out.printf("样本 %d 个，逐位完全相同 %d 个 (%.2f%%)，不同 %d 个%n",
                n, exact, 100.0 * exact / n, n - exact);
        System.out.printf("最大绝对误差 %.3e%n", maxAbs);
        System.out.printf("  出现在 x=%.17g%n", maxX);
        System.out.printf("  python=%.17g%n  jvm   =%.17g%n", maxPy, maxJv);
        System.out.printf("最大 ULP 偏差 %d%n", maxUlp);
        System.out.printf("→ 换算到最大位移（hop amp=16px）：%.3e px%n", maxAbs * 16.0);
        System.out.printf("→ 换算到最小尺寸位移（scale=0.5）：%.3e px%n", maxAbs * 0.5);
    }

    static void probeCube(Path p) throws Exception {
        List<String> lines = Files.readAllLines(p, StandardCharsets.UTF_8);
        int n = 0;
        int exactMul = 0, exactPow = 0;
        double maxAbsMul = 0.0, maxAbsPow = 0.0;
        long maxUlpMul = 0, maxUlpPow = 0;

        for (String line : lines) {
            if (line.isEmpty()) continue;
            String[] parts = line.split("\t");
            double x = Double.parseDouble(parts[0]);
            double py = Double.parseDouble(parts[1]);
            n++;

            double mul = x * x * x;
            double pow = Math.pow(x, 3.0);

            if (Double.doubleToRawLongBits(py) == Double.doubleToRawLongBits(mul)) exactMul++;
            if (Double.doubleToRawLongBits(py) == Double.doubleToRawLongBits(pow)) exactPow++;

            maxAbsMul = Math.max(maxAbsMul, Math.abs(py - mul));
            maxAbsPow = Math.max(maxAbsPow, Math.abs(py - pow));
            maxUlpMul = Math.max(maxUlpMul, ulpDiff(py, mul));
            maxUlpPow = Math.max(maxUlpPow, ulpDiff(py, pow));
        }

        System.out.println("== x**3  (Python)  vs  JVM 两种写法 ==");
        System.out.printf("样本 %d 个%n", n);
        System.out.printf("  x*x*x           逐位相同 %d (%.2f%%)  最大 ULP %d  最大误差 %.3e%n",
                exactMul, 100.0 * exactMul / n, maxUlpMul, maxAbsMul);
        System.out.printf("  Math.pow(x,3.0) 逐位相同 %d (%.2f%%)  最大 ULP %d  最大误差 %.3e%n",
                exactPow, 100.0 * exactPow / n, maxUlpPow, maxAbsPow);
        System.out.println();
        if (maxUlpMul <= maxUlpPow) {
            System.out.printf("→ 结论：x*x*x 更接近 CPython（ULP 偏差 %d vs %d）%n", maxUlpMul, maxUlpPow);
        } else {
            System.out.printf("→ 结论：Math.pow(x,3.0) 更接近 CPython（ULP 偏差 %d vs %d）%n", maxUlpPow, maxUlpMul);
        }
        System.out.printf("→ sink 位移 amp=11px，误差换算：%.3e px%n",
                Math.min(maxAbsMul, maxAbsPow) * 11.0);
    }
}
