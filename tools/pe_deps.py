# -*- coding: utf-8 -*-
r"""读 PE 导入表并算 DLL 传递闭包 —— 用来验证"精简 Qt 清单是否覆盖了硬依赖"。

手写一份 DLL 白名单很容易漏（漏了在别人机器上就是启动即挂、而且没有报错）。
所以不靠人眼核对：解析每个 .pyd/.dll 的导入表，把 Qt5/bin 里的闭包算出来，
和清单对比。**在闭包里但不在清单里的，就是漏了。**

区分硬导入（Import Directory，index 1）和延迟导入（Delay Import Descriptor，index 13）：
- 硬导入缺了 → 加载该 DLL 直接失败，必须带上。
- 延迟导入只在真的调用到那个函数时才加载 → 不一定要带
  （Qt 的 TLS、软件 OpenGL、ANGLE 都是延迟导入，带了反而白白多几十 MB）。

用法:
    python tools/pe_deps.py            # 打印各 DLL 的依赖 + 闭包
    from pe_deps import closure, MissingDep
"""
import os
import struct

# 系统 DLL：一定在目标机器上，不需要随包携带
SYSTEM = {
    "kernel32.dll", "user32.dll", "advapi32.dll", "ole32.dll", "oleaut32.dll",
    "gdi32.dll", "gdi32full.dll", "shell32.dll", "ws2_32.dll", "winmm.dll",
    "comdlg32.dll", "version.dll", "dwmapi.dll", "uxtheme.dll", "imm32.dll",
    "winspool.drv", "mpr.dll", "crypt32.dll", "dnsapi.dll", "iphlpapi.dll",
    "secur32.dll", "setupapi.dll", "wtsapi32.dll", "rpcrt4.dll", "shlwapi.dll",
    "comctl32.dll", "powrprof.dll", "propsys.dll", "d3d11.dll", "dxgi.dll",
    "opengl32.dll", "glu32.dll", "winhttp.dll", "wininet.dll", "pdh.dll",
    "bcrypt.dll", "ncrypt.dll", "ntdll.dll", "msvcrt.dll", "msimg32.dll",
    "d3d9.dll", "dxva2.dll", "evr.dll", "gdiplus.dll", "quartz.dll",
    "shcore.dll", "dwrite.dll", "dcomp.dll", "windowscodecs.dll", "wlanapi.dll",
    "dhcpcsvc.dll", "bluetoothapis.dll", "bthprops.cpl", "wer.dll",
    "dbghelp.dll", "psapi.dll", "normaliz.dll", "mswsock.dll", "avrt.dll",
    "dsound.dll", "msacm32.dll", "ksuser.dll", "mf.dll", "mfplat.dll",
    "mfreadwrite.dll", "hid.dll", "cfgmgr32.dll", "twinapi.dll",
    "twinapi.appcore.dll", "wtsapi32.dll", "userenv.dll", "netapi32.dll",
    # Windows Core Audio —— qtaudio_wasapi.dll 的硬依赖
    "mmdevapi.dll", "audioses.dll", "wdmaud.drv", "midimap.dll",
    # CPython 自己的 DLL：随解释器一起给，不由包里的 Qt 清单负责
    "python3.dll", "python313.dll", "python312.dll", "python311.dll",
    "python310.dll", "python39.dll",
}


def _sections(d, e_lfanew):
    coff = e_lfanew + 4
    nsec, = struct.unpack_from("<H", d, coff + 2)
    optsz, = struct.unpack_from("<H", d, coff + 16)
    opt = coff + 20
    secs, so = [], opt + optsz
    for i in range(nsec):
        b = so + i * 40
        vsz, va, rsz, ro = struct.unpack_from("<IIII", d, b + 8)
        secs.append((va, vsz, ro, rsz))
    return opt, secs


def imports(path):
    """返回 (硬导入, 延迟导入) 两个小写 DLL 名列表。"""
    try:
        with open(path, "rb") as f:
            d = f.read()
    except OSError:
        return [], []
    if len(d) < 0x40 or d[:2] != b"MZ":
        return [], []
    e_lfanew, = struct.unpack_from("<I", d, 0x3C)
    if d[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return [], []

    opt, secs = _sections(d, e_lfanew)
    magic, = struct.unpack_from("<H", d, opt)
    dd = opt + (112 if magic == 0x20B else 96)
    nrva, = struct.unpack_from("<I", d, dd - 4)

    def off(rva):
        for va, vsz, ro, rsz in secs:
            if va <= rva < va + max(vsz, rsz):
                return ro + (rva - va)
        return None

    def walk(index):
        """index=1 硬导入 / index=13 延迟导入。

        两个结构的字段位置不一样，别混：
          IMAGE_IMPORT_DESCRIPTOR（20B）：OriginalFirstThunk(+0) / TimeDateStamp(+4)
                                          / ForwarderChain(+8) / **Name(+12)** / FirstThunk(+16)
          ImgDelayDescr       （32B）：Attributes(+0) / **DllNameRVA(+4)** / ...
        读错字段会得到一串看着像字符串的垃圾，而且**不会报错**（踩过：读到
        0 个依赖，看起来像"没有依赖"，其实解析全错）。
        """
        if nrva <= index:
            return []
        rva, _sz = struct.unpack_from("<II", d, dd + index * 8)
        if not rva:
            return []
        base = off(rva)
        if base is None:
            return []
        out, step = [], 32 if index == 13 else 20
        for i in range(4096):                       # 上限防跑飞
            ent = base + i * step
            if ent + step > len(d):
                break
            if index == 13:
                _a, namerva = struct.unpack_from("<II", d, ent)
            else:
                namerva, = struct.unpack_from("<I", d, ent + 12)
            if not namerva:
                break
            o = off(namerva)
            if o is None or o >= len(d):
                break
            end = d.find(b"\0", o)
            if end < 0:
                break
            name = d[o:end].decode("ascii", "replace").lower()
            if not name or "." not in name:         # 只认像 DLL 名字的，挡掉解析跑偏
                break
            out.append(name)
        return out

    return walk(1), walk(13)


def closure(seeds, bin_dir, system=None):
    """从 seeds 出发算硬依赖闭包，只保留 bin_dir 里有的。

    返回 (needed, missing)：
        needed  —— 闭包内、位于 bin_dir 的文件名（小写）集合
        missing —— 既不在 bin_dir、也不在系统名单里的依赖 {名字: [引用它的文件]}
    """
    system = system or SYSTEM
    have = {f.lower() for f in os.listdir(bin_dir)} if os.path.isdir(bin_dir) else set()
    needed, missing, seen, stack = set(), {}, set(), list(seeds)
    while stack:
        p = stack.pop()
        key = os.path.basename(p).lower()
        if key in seen or not os.path.exists(p):
            continue
        seen.add(key)
        hard, _delay = imports(p)
        for name in hard:
            if name.startswith("api-ms-win") or name.startswith("ext-ms-"):
                continue
            if name in have:
                needed.add(name)
                stack.append(os.path.join(bin_dir, name))
            elif name not in system:
                missing.setdefault(name, []).append(key)
    return needed, missing


if __name__ == "__main__":
    SP = r"C:\Users\air\.workbuddy\binaries\python\envs\default\Lib\site-packages"
    BIN = os.path.join(SP, "PyQt5", "Qt5", "bin")
    seeds = [os.path.join(SP, "PyQt5", x) for x in
             ("QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtMultimedia.pyd")]
    seeds += [os.path.join(BIN, f) for f in
              ("Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll", "Qt5Multimedia.dll")]
    needed, missing = closure(seeds, BIN)
    print("闭包内位于 Qt5/bin 的 DLL：")
    tot = 0
    for n in sorted(needed):
        s = os.path.getsize(os.path.join(BIN, n))
        tot += s
        print(f"  {s / 1048576:6.2f} MB  {n}")
    print(f"  ----> {tot / 1048576:.1f} MB")
    print("非系统又找不到的依赖：", missing or "无")
