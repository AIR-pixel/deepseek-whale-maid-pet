# -*- coding: utf-8 -*-
"""内容更新器：零费用、启动时检查一次。

为什么是"启动时查一次"而不是常驻轮询
------------------------------------
真·实时推送要长连接常驻（心跳、重连、还得有个服务端），对桌宠这种场景
代价远大于收益。这东西本来就是开机自启的，所以"每次启动查一次"在用户感知上
和实时没差别，代价是零 —— 不新开定时器、不常驻联网。

三个免费通道，按顺序试，谁通用谁
--------------------------------
1. ``raw.githubusercontent.com``  实时、无缓存延迟，但国内链路时通时断
2. ``cdn.jsdelivr.net``           全球 CDN，国内基本可达；代价是最长 12 小时缓存
3. ``cdn.gh-proxy.com``           第三方镜像，前面下载素材时验证过能用

顺序刻意把 raw 放第一：能直连的用户立刻拿到最新内容；不能的走 jsDelivr 也只是
慢半天，而"惊喜"不要求分钟级时效。

安全边界（这些是硬约束，不是建议）
----------------------------------
* **只下数据文件**（``.json`` / ``.webp``），其余扩展名一律拒绝。
  程序侧只解释数据、不执行任何下发内容 —— 最坏情况是动作难看，不会变成执行任意代码。
* **清单里的路径必须相对、无 ``..``**，防目录穿越。
* **每个文件校验 SHA256**，对不上整包丢弃。校验失败绝不"先装上再说"。
* **先在内存里下完并全部校验通过，才一次性落盘**。中途失败磁盘上不留半成品。
* **素材先写、``actions.json`` 最后写**。索引文件最后落地，它引用到的素材必然已就位。
* 任何失败都静默返回，不弹窗、不阻塞启动。检查更新是锦上添花，不是启动的必经环节。
"""
import hashlib
import json
import os
import queue
import shutil
import threading
import time
import urllib.error
import urllib.request

import contentpack

APP_VERSION = "1.1.0"
REPO = "AIR-pixel/deepseek-whale-maid-pet"
BRANCH = "main"

RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/content/"
JSDELIVR = f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/content/"
GHPROXY = f"https://cdn.gh-proxy.com/https://raw.githubusercontent.com/{REPO}/{BRANCH}/content/"

DEFAULT_SOURCES = (RAW, JSDELIVR, GHPROXY)

MANIFEST = "manifest.json"
INDEX = "actions.json"

TIMEOUT = 5.0                     # 单次请求超时（秒）
MAX_FILE = 4 * 1024 * 1024        # 单个文件上限
MAX_TOTAL = 24 * 1024 * 1024      # 一次更新的总量上限
ALLOWED_SUFFIX = (".json", ".webp")
UA = f"DeepSeekPet/{APP_VERSION} (+https://github.com/{REPO})"


class UpdateResult:
    """一次检查的结果。status 取值：

    ``updated``     装上了新内容
    ``up-to-date``  已是最新
    ``offline``     三个通道都不通（正常情况，不是错误）
    ``failed``      拿到了清单但过程出错，磁盘未改动
    ``skipped``     内容要求的程序版本比当前高
    ``disabled``    用户没开启接收新内容
    """

    def __init__(self, status, version=0, added=(), message="", announce=None):
        self.status = status
        self.version = version
        self.added = tuple(added)
        self.message = message or status
        self.announce = announce

    def ok(self):
        return self.status in ("updated", "up-to-date")

    def __repr__(self):
        return (f"<UpdateResult {self.status} v{self.version} "
                f"added={list(self.added)} {self.message!r}>")


# ---------------------------------------------------------------- 网络

def default_sources():
    """测试用 DPET_UPDATE_BASE 指到本地服务，避免真联网。"""
    base = os.environ.get("DPET_UPDATE_BASE")
    if base:
        return (base if base.endswith("/") else base + "/",)
    return DEFAULT_SOURCES


_OPENER = None


def _opener():
    """尊重系统代理设置，进程内复用同一个 opener。

    国内用户很可能得靠系统代理才能访问 raw.githubusercontent，所以不能粗暴禁用。
    真遇到环境变量里的代理把请求带歪（比如带着 http_proxy 启动），用 DPET_NO_PROXY=1
    强制直连来排错。
    """
    global _OPENER
    if _OPENER is None:
        if os.environ.get("DPET_NO_PROXY"):
            _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        else:
            _OPENER = urllib.request.build_opener()
    return _OPENER


def _fetch(url, limit=MAX_FILE):
    """取回一个 URL 的字节内容。失败抛异常，由调用方决定换源还是放弃。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Cache-Control": "no-cache",
    })
    with _opener().open(req, timeout=TIMEOUT) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"响应超过上限 {limit} 字节")
    return data


def _get_manifest(sources):
    """依次尝试各通道，返回 (清单 dict, 命中的源前缀)；全失败返回 (None, None)"""
    for base in sources:
        try:
            raw = _fetch(base + MANIFEST, limit=256 * 1024)
            return json.loads(raw.decode("utf-8")), base
        except Exception:            # noqa: BLE001 — 任何失败都换下一个源，不透传原因
            continue
    return None, None


# ---------------------------------------------------------------- 工具

def _safe_relpath(rel):
    """把清单里的相对路径规范化，不合法返回 None。

    拒绝绝对路径、盘符、``..`` 段、以及不在白名单里的扩展名。
    这几条同时挡住目录穿越和"下发一个 .exe"。
    """
    if not isinstance(rel, str):
        return None
    rel = rel.replace("\\", "/").strip()
    if not rel or rel.startswith("/") or ":" in rel:
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if not rel.lower().endswith(ALLOWED_SUFFIX):
        return None
    return "/".join(parts)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ver_tuple(s):
    try:
        return tuple(int(x) for x in str(s).split("."))
    except (TypeError, ValueError):
        return (0,)


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)                  # 同目录 rename 是原子的


# ---------------------------------------------------------------- 主流程

def check_and_update(current_version=0, user_dir=None, sources=None,
                     app_version=APP_VERSION):
    """检查并安装新内容。**任何异常都不往外抛**，一律转成 UpdateResult。"""
    sources = tuple(sources or default_sources())
    user_dir = user_dir or contentpack.user_content_dir()

    manifest, base = _get_manifest(sources)
    if manifest is None:
        return UpdateResult("offline", current_version, message="三个通道均不可达")

    try:
        version = int(manifest.get("content_version", 0) or 0)
    except (TypeError, ValueError):
        return UpdateResult("failed", current_version, message="清单版本号不合法")

    if version <= current_version:
        return UpdateResult("up-to-date", current_version, message=f"已是最新 r{version}")

    app_min = manifest.get("app_min")
    if app_min and _ver_tuple(app_min) > _ver_tuple(app_version):
        return UpdateResult("skipped", current_version,
                            message=f"内容需要程序 {app_min} 以上，当前 {app_version}")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return UpdateResult("failed", current_version, message="清单里没有文件表")

    plan = {}
    for rel, meta in files.items():
        safe = _safe_relpath(rel)
        if safe is None:
            return UpdateResult("failed", current_version, message=f"清单路径不合法: {rel!r}")
        if not isinstance(meta, dict) or not meta.get("sha256"):
            return UpdateResult("failed", current_version, message=f"缺少校验值: {safe}")
        plan[safe] = meta

    if INDEX not in plan:
        return UpdateResult("failed", current_version, message="清单里没有 actions.json")

    # 内容要引用到素材，素材必须先到位，所以索引文件排最后写。
    order = sorted(plan, key=lambda r: (r == INDEX, r))

    # 先全部下到内存并校验，全通过才落盘 —— 中途失败磁盘上不留半成品。
    staged, total = {}, 0
    for rel in order:
        meta = plan[rel]
        try:
            data = _fetch(base + rel)
        except Exception as e:                          # noqa: BLE001
            return UpdateResult("failed", current_version, message=f"下载 {rel} 失败: {e}")
        total += len(data)
        if total > MAX_TOTAL:
            return UpdateResult("failed", current_version, message="内容总量超过上限")
        if sha256(data) != str(meta["sha256"]).lower():
            return UpdateResult("failed", current_version,
                                message=f"{rel} 校验不通过，整包已丢弃")
        staged[rel] = data

    # 先在 staging 目录里完整落一遍并**真实加载一次**，通过了才搬进正式目录。
    # 光校验 SHA256 不够：清单本身漏写一个素材时，每个文件都能对上哈希，
    # 但装上去的包是残的（actions.json 引用了不存在的图）。这种只能靠实跑来发现。
    staging = user_dir.rstrip("\\/") + ".staging"
    shutil.rmtree(staging, ignore_errors=True)      # 清掉上次崩溃可能留下的残骸
    try:
        for rel in order:
            _atomic_write(os.path.join(staging, *rel.split("/")), staged[rel])
    except OSError as e:
        shutil.rmtree(staging, ignore_errors=True)
        return UpdateResult("failed", current_version, message=f"暂存失败: {e}")

    probe = contentpack.load(user_dir=staging)
    if probe.problems:
        shutil.rmtree(staging, ignore_errors=True)
        return UpdateResult("failed", current_version,
                            message="新内容自检不过，已放弃: " + "; ".join(probe.problems[:3]))

    # 逐字节比对，只搬真正变化的文件。版本号变了但文件没变的情况（只改了台词、
    # 或者只动了清单）会走"一个都没搬"的分支，此时只更新 installed.json 里的版本号，
    # 否则每次启动都会把同一份东西重下一遍。
    written = []
    try:
        for rel in order:
            dst = os.path.join(user_dir, *rel.split("/"))
            if _same_file(dst, staged[rel]):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(staging, *rel.split("/")), dst)   # 同盘 rename，原子
            written.append(rel)
    except OSError as e:
        shutil.rmtree(staging, ignore_errors=True)
        return UpdateResult("failed", current_version, message=f"写入失败: {e}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    try:
        _atomic_write(os.path.join(user_dir, contentpack.INSTALLED_NAME),
                      json.dumps({
                          "content_version": version,
                          "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "source": base,
                          "files": {r: plan[r]["sha256"] for r in plan},
                      }, ensure_ascii=False, indent=2).encode("utf-8"))
    except OSError:
        pass                                     # 记录写不上不影响内容生效

    return UpdateResult("updated", version, added=written,
                        message=f"已更新到 r{version}",
                        announce=manifest.get("announce"))


def _same_file(path, data):
    try:
        with open(path, "rb") as f:
            return f.read() == data
    except OSError:
        return False


def rollback(user_dir=None):
    """把远端内容整个丢掉，退回内置。菜单里的"回滚"就是删这一个目录。"""
    d = user_dir if user_dir is not None else contentpack.user_content_dir()
    try:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(d.rstrip("\\/") + ".staging", ignore_errors=True)
        return not os.path.isdir(d)
    except OSError:
        return False


# ---------------------------------------------------------------- 线程封装

class Updater:
    """把一次检查丢到后台线程，结果放在队列里让主线程自己取。

    刻意不用 Qt 的信号跨线程：桌宠主循环本来就是 25fps 的 QTimer，
    在里面顺手 poll 一下最简单，也省掉"槽函数被在非 GUI 线程执行"的风险。
    """

    def __init__(self, current_version=0, user_dir=None, sources=None,
                 enabled=True, delay=4.0):
        self.current_version = current_version
        self.user_dir = user_dir
        self.sources = sources
        self.enabled = enabled
        self.delay = delay
        self._q = queue.Queue()
        self._started = False
        self.running = False

    def start(self):
        if self._started or not self.enabled:
            return
        self._started = True
        t = threading.Thread(target=self._run, name="dpet-updater", daemon=True)
        self.running = True
        t.start()

    def _run(self):
        try:
            time.sleep(self.delay)        # 别和首帧、问候音抢启动那一下
            res = check_and_update(self.current_version, self.user_dir, self.sources)
        except Exception as e:                                    # noqa: BLE001
            res = UpdateResult("failed", self.current_version, message=str(e))
        self.running = False
        self._q.put(res)

    def poll(self):
        """主线程调用。有结果就返回，没有返回 None。"""
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None
