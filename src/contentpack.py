# -*- coding: utf-8 -*-
"""内容包：内置内容与远端下发内容的合并加载。

分层
----
内置   ``<程序目录>/content/actions.json`` + ``<程序目录>/assets/``
       随包发布、只读。程序升级才会变。

远端   ``%LOCALAPPDATA%/DeepSeekPet/content/``
       更新器下载的东西落这儿，可整体删除回滚。

远端按**条目**覆盖内置：同名素材 / 同名动作 / 同名状态被替换，新名字追加。
合并完成后整体自检（每个状态的每一帧素材是否都能找到、动效定义是否能求值），
任何一处不过关就**把远端整包丢掉**、退回内置 —— 不做部分接受。
半残的内容包会表现为"某个动作突然不动了""点了没反应"，比"没更新"难查得多。

为什么远端落在 LOCALAPPDATA 而不是程序目录：程序可能被装在 ``Program Files``
下，那个目录对普通用户不可写，更新会静默失败（这个坑在别的整合包上踩过）。
"""
import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN_CONTENT = os.path.join(APP_DIR, "content")
BUILTIN_ASSETS = os.path.join(APP_DIR, "assets")

APP_NAME = "DeepSeekPet"
INSTALLED_NAME = "installed.json"

# 状态条目里允许出现的字段。多出来的字段一律忽略，这样新版本加字段后
# 老程序不会因为看不懂而拒绝整包。
STATE_KEYS = ("frames", "temp", "dur", "cue", "lines", "weight", "announce")


def user_content_dir():
    """远端内容的落地目录。

    测试用 ``DPET_USER_CONTENT`` 指到临时目录，避免污染真实安装。
    """
    override = os.environ.get("DPET_USER_CONTENT")
    if override:
        return override
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, APP_NAME, "content")


class ContentPack:
    """合并后的最终内容。构造后不可变。"""

    def __init__(self, assets, motions, states, asset_roots,
                 source="builtin", version=1, announce=None, problems=None,
                 overlays=()):
        self.assets = assets
        self.motions = motions
        self.states = states
        self.asset_roots = list(asset_roots)
        self.source = source            # "builtin" 或 "builtin+remote"
        self.version = version
        self.announce = announce        # 新内容首次生效时的台词，没有就是 None
        self.problems = list(problems or [])
        self.overlays = tuple(overlays)  # 远端新增/覆盖了哪些条目，供菜单展示

    # ------------------------------------------------------------ 素材
    def asset_path(self, name):
        """素材名 -> 绝对路径。远端优先，内置兜底，都找不到返回 None。"""
        meta = self.assets.get(name)
        if not meta:
            return None
        rel = meta.get("file") or (name + ".webp")
        parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
        for root in self.asset_roots:
            cand = os.path.join(root, *parts)
            if os.path.isfile(cand):
                return cand
        return None

    def visual_scale(self, name):
        meta = self.assets.get(name)
        if not meta:
            return 1.0
        try:
            return float(meta.get("visual_scale", 1.0))
        except (TypeError, ValueError):
            return 1.0

    def frame_names(self):
        return sorted(self.assets)

    # ------------------------------------------------------------ 状态
    def states_for_pet(self):
        """转成 PetWindow.STATES 的老格式：{名字: (frames, temp, dur)}"""
        out = {}
        for name, st in self.states.items():
            frames = list(st.get("frames") or ())
            if not frames:
                continue
            dur = st.get("dur")
            out[name] = (frames, bool(st.get("temp", False)),
                         tuple(dur) if dur else None)
        return out

    def state_meta(self, name):
        return self.states.get(name) or {}

    # ------------------------------------------------------------ 自检
    def validate(self):
        """返回问题列表。空列表 = 合格。

        检查两件事，都是"能真正跑起来"的必要条件：
        1. 每个状态引用的素材必须存在（找不到 WebP 会在渲染时才炸，那时已经晚了）
        2. 动效定义必须能求值（ref 引用了不存在的信号之类）

        宁可在这里把整包否掉，也不要等用户看到"点了没反应"再来查。
        """
        bad = []
        for name, st in self.states.items():
            if isinstance(st, tuple):           # 已经是老格式，跳过
                continue
            frames = list(st.get("frames") or ())
            if not frames:
                bad.append(f"状态 {name} 没有可用帧")
                continue
            for f in frames:
                if f not in self.assets:
                    bad.append(f"状态 {name} 引用了未定义的素材 {f}")
                elif self.asset_path(f) is None:
                    bad.append(f"素材文件缺失: {f}")
        try:
            ms = self.motion_set()
            for st in self.states.values():
                if isinstance(st, tuple):
                    continue
                for f in st.get("frames") or ():
                    if ms.has(f):
                        ms.raw(f, 0.0)          # 触发一次求值，ref 写错会在这里抛
        except Exception as e:
            bad.append(f"动效定义无法求值: {e}")
        return bad

    def motion_set(self):
        """构造动效集合（不缓存，调用方自己持有以支持热替换）"""
        import motion
        vis = {k: self.visual_scale(k) for k in self.assets}
        return motion.MotionSet(self.motions, vis)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _merge(base, extra):
    """按条目浅合并，返回 (合并结果, 被覆盖/新增的键)"""
    out = dict(base)
    changed = []
    for k, v in (extra or {}).items():
        if k not in out or out[k] != v:
            changed.append(k)
        out[k] = v
    return out, changed


def load(builtin_content=BUILTIN_CONTENT, user_dir=None, builtin_assets=BUILTIN_ASSETS):
    """加载内容包。

    永远返回一个可用的 ContentPack：内置坏了也返回空包而不是抛异常，
    动效全静默总好过桌宠起不来。
    """
    problems = []

    try:
        builtin = _read_json(os.path.join(builtin_content, "actions.json"))
    except Exception as e:
        builtin = {}
        problems.append(f"内置内容包读取失败: {e}")

    assets = dict(builtin.get("assets") or {})
    motions = dict(builtin.get("motions") or {})
    states = dict(builtin.get("states") or {})
    version = int(builtin.get("content_version", 1) or 1)
    announce = None
    overlays = []

    remote_dir = user_dir if user_dir is not None else user_content_dir()
    remote_file = os.path.join(remote_dir, "actions.json")
    source = "builtin"

    if os.path.isfile(remote_file):
        try:
            remote = _read_json(remote_file)
            r_assets = dict(remote.get("assets") or {})
            r_motions = dict(remote.get("motions") or {})
            r_states = dict(remote.get("states") or {})

            m_assets, c1 = _merge(assets, r_assets)
            m_motions, c2 = _merge(motions, r_motions)
            m_states, c3 = _merge(states, r_states)

            probe = ContentPack(m_assets, m_motions, m_states,
                                [remote_dir, builtin_assets],
                                version=int(remote.get("content_version", version) or version),
                                announce=remote.get("announce"))
            bad = probe.validate()
            if bad:
                problems.extend(f"远端内容包不合格，已整包丢弃: {b}" for b in bad)
            else:
                assets, motions, states = m_assets, m_motions, m_states
                version = probe.version
                announce = remote.get("announce")
                overlays = sorted(set(c1) | set(c2) | set(c3))
                source = "builtin+remote"
        except Exception as e:
            problems.append(f"远端内容包读取失败，已忽略: {e}")

    pack = ContentPack(assets, motions, states,
                       [remote_dir, builtin_assets] if source == "builtin+remote"
                       else [builtin_assets],
                       source=source, version=version, announce=announce,
                       problems=problems, overlays=overlays)
    pack.problems.extend(pack.validate())
    return pack


def installed_info(user_dir=None):
    """读取已安装内容的记录（更新器写的），没有就返回 None"""
    d = user_dir if user_dir is not None else user_content_dir()
    try:
        return _read_json(os.path.join(d, INSTALLED_NAME))
    except Exception:
        return None
