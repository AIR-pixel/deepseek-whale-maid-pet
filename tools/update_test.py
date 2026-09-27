# -*- coding: utf-8 -*-
"""内容更新链路端到端测试。

不碰真实网络：在本地起一个静态服务当内容源，模拟"发布一批新内容"的全过程。
覆盖六件事 ——

1. 首次安装：清单 -> 校验 -> 落盘 -> 内容包能加载出新动作
2. 幂等：再查一次必须是 up-to-date，且不重复下载
3. 篡改：文件与 SHA256 对不上时必须整包拒绝，且磁盘上不能有半成品
4. 目录穿越：清单里塞 ``../evil.json`` 必须被挡
5. 非数据文件：清单里塞 ``.exe`` 必须被挡
6. 回滚：删掉远端目录后退回内置内容

用法：``python tools/update_test.py``
"""
import functools
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

FAIL = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode, **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
        f.write(data)


# ---------------------------------------------------------------- 测试站点

REMOTE_ACTIONS = {
    "schema": 1,
    "content_version": 2,
    "announce": "我学会新动作了！",
    "assets": {"stretch": {"file": "pet/stretch.webp", "visual_scale": 1.0}},
    "motions": {"stretch": {
        "cycle": 2.2,
        "channels": {
            "dy": [{"k": "sine", "period": 2.2, "amp": 6.0}],
            "sy": [{"k": "sine", "period": 1.1, "amp": 0.02}],
        },
    }},
    "states": {"stretch": {
        "frames": ["stretch"], "temp": True, "dur": [2200, 2800],
        "cue": "happy", "lines": ["伸个懒腰……好了，继续干活。"], "weight": 3,
    }},
}


def build_site(site, tamper=None, evil_path=None):
    """铺一个内容源目录。tamper 用来故意写坏某个文件的字节。"""
    cdir = os.path.join(site, "content")
    shutil.rmtree(site, ignore_errors=True)

    actions_bytes = json.dumps(REMOTE_ACTIONS, ensure_ascii=False,
                               indent=2).encode("utf-8")
    # 素材用现成的一张立绘顶着，测的是链路不是画风
    src_webp = os.path.join(ROOT, "assets", "pet", "happy.webp")
    webp_bytes = open(src_webp, "rb").read()

    files = {
        "actions.json": actions_bytes,
        "pet/stretch.webp": webp_bytes,
    }

    manifest = {
        "content_version": 2,
        "app_min": "1.0.0",
        "announce": REMOTE_ACTIONS["announce"],
        "files": {},
    }
    for rel, data in files.items():
        digest = updater.sha256(data).upper() if tamper == "case" else updater.sha256(data)
        manifest["files"][rel] = {"sha256": digest, "bytes": len(data)}

    if tamper == "file":
        files["pet/stretch.webp"] = webp_bytes + b"corrupted"
    if tamper == "missing":
        del manifest["files"]["pet/stretch.webp"]
    if evil_path:
        manifest["files"][evil_path] = {"sha256": updater.sha256(b"x"), "bytes": 1}

    for rel, data in files.items():
        write(os.path.join(cdir, *rel.split("/")), data)
    write(os.path.join(cdir, "manifest.json"),
          json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(directory):
    handler = functools.partial(_Quiet, directory=directory)
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/content/"


# ---------------------------------------------------------------- 跑测

sys.path.insert(0, SRC)
import contentpack  # noqa: E402
import updater      # noqa: E402

TMP = tempfile.mkdtemp(prefix="dpet_update_")
SITE = os.path.join(TMP, "site")
USER = os.path.join(TMP, "user")
os.environ["DPET_NO_PROXY"] = "1"          # 本地服务不该被系统代理带走

try:
    # ---------------------------------------------------------- 1 首次安装
    print("[1] 首次安装")
    build_site(SITE)
    srv, base = serve(SITE)
    env_base = os.environ.get("DPET_UPDATE_BASE")
    os.environ["DPET_UPDATE_BASE"] = base

    res = updater.check_and_update(0, user_dir=USER)
    print(f"     {res!r}")
    check(res.status == "updated", f"首次应装上，实际 {res.status}: {res.message}")
    check(res.version == 2, f"版本应为 2，实际 {res.version}")
    check(os.path.isfile(os.path.join(USER, "actions.json")), "actions.json 已落盘")
    check(os.path.isfile(os.path.join(USER, "pet", "stretch.webp")), "新素材已落盘")
    check(os.path.isfile(os.path.join(USER, "installed.json")), "安装记录已写入")
    check(res.announce == REMOTE_ACTIONS["announce"], f"惊喜台词 = {res.announce!r}")

    # 索引文件必须最后写：写它的时候素材必然已就位
    check(res.added[-1] == "actions.json" if res.added else False,
          f"落盘顺序 actions.json 在最后 = {list(res.added)}")

    info = contentpack.installed_info(USER)
    check(info and info.get("content_version") == 2, f"安装记录版本 = {info}")

    # ---------------------------------------------------------- 2 内容生效
    print("[2] 内容包加载出远端新动作")
    pack = contentpack.load(user_dir=USER)
    check(pack.source == "builtin+remote", f"来源 = {pack.source}")
    check(pack.problems == [], f"自检无问题 | {pack.problems}")
    check("stretch" in pack.states, f"新状态已合并 = {sorted(pack.states)}")
    check(len(pack.states) == 9, f"状态数 8 + 1 = {len(pack.states)}")
    check(pack.asset_path("stretch") is not None, "远端素材可解析")
    check(pack.asset_path("idle_open") is not None, "内置素材仍可解析（未被覆盖）")
    ms = pack.motion_set()
    check(ms.has("stretch") and ms.unknown == [], f"新动效可求值，未知原语 = {ms.unknown}")
    d0 = ms.params("stretch", 0.0, 1.0)
    d1 = ms.params("stretch", 0.55, 1.0)
    check(d0 != d1, f"新动作真的在动: {d0} -> {d1}")
    check(pack.state_meta("stretch").get("lines"), "新动作自带台词")

    # ---------------------------------------------------------- 3 幂等
    print("[3] 重复检查")
    res2 = updater.check_and_update(2, user_dir=USER)
    check(res2.status == "up-to-date", f"应是最新，实际 {res2.status}: {res2.message}")
    check(res2.added == (), f"没有重复落盘 = {list(res2.added)}")

    # ---------------------------------------------------------- 4 篡改
    print("[4] 篡改必须被拒")
    for label, kwargs, why in (
        ("数据被改", {"tamper": "file"}, "文件与 SHA256 对不上"),
        ("缺文件表项", {"tamper": "missing"}, "清单少写一个文件"),
    ):
        build_site(SITE, **kwargs)
        before = sorted(os.listdir(USER))
        r = updater.check_and_update(0, user_dir=USER)
        check(r.status == "failed", f"{label} -> {why}，实际 {r.status}")
        after = sorted(os.listdir(USER))
        check(before == after, f"{label} 后磁盘未被改动 = {after}")

    # 大小写不敏感的十六进制也应接受
    build_site(SITE, tamper="case")
    r = updater.check_and_update(0, user_dir=USER)
    check(r.status == "updated", f"大写 SHA256 也应通过，实际 {r.status}: {r.message}")

    # ---------------------------------------------------------- 5 路径穿越
    print("[5] 恶意路径必须被挡")
    for evil in ("../evil.json", "/abs/evil.json", "C:/evil.json",
                 "pet/payload.exe", "pet/../../evil.webp"):
        build_site(SITE, evil_path=evil)
        r = updater.check_and_update(0, user_dir=USER)
        check(r.status == "failed", f"拒绝 {evil!r}，实际 {r.status}: {r.message}")

    # ---------------------------------------------------------- 6 回滚
    print("[6] 回滚到内置")
    build_site(SITE)
    updater.check_and_update(0, user_dir=USER)
    check(os.path.isdir(USER), "远端目录存在")
    check(updater.rollback(USER), "回滚成功")
    check(not os.path.isdir(USER), "远端目录已删除")
    pack = contentpack.load(user_dir=USER)
    check(pack.source == "builtin", f"退回内置 = {pack.source}")
    check("stretch" not in pack.states, "新动作已消失")
    check(len(pack.states) == 8, f"状态数回到 8 = {len(pack.states)}")

    # ---------------------------------------------------------- 7 断网
    print("[7] 通道不通时不报错")
    srv.shutdown()
    r = updater.check_and_update(0, user_dir=USER)
    check(r.status == "offline", f"应判为离线，实际 {r.status}: {r.message}")

    # ---------------------------------------------------------- 8 线程封装
    print("[8] 后台线程封装")
    build_site(SITE)
    srv2, base2 = serve(SITE)
    os.environ["DPET_UPDATE_BASE"] = base2
    up = updater.Updater(0, user_dir=USER, delay=0.05)
    up.start()
    got = None
    for _ in range(200):
        got = up.poll()
        if got is not None:
            break
        import time
        time.sleep(0.05)
    check(got is not None and got.status == "updated", f"线程版结果 = {got!r}")
    check(not up.running, "线程已收尾")
    check(up.poll() is None, "结果只取一次")
    srv2.shutdown()

    # 关闭开关时不应发起任何请求
    up2 = updater.Updater(0, user_dir=USER, enabled=False, delay=0.01)
    up2.start()
    check(not up2.running and up2.poll() is None, "开关关闭时不检查")

finally:
    if env_base is None:
        os.environ.pop("DPET_UPDATE_BASE", None)
    else:
        os.environ["DPET_UPDATE_BASE"] = env_base
    shutil.rmtree(TMP, ignore_errors=True)

print()
if FAIL:
    print(f"== {len(FAIL)} 项失败 ==")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("== 全部通过 ==")
