# -*- coding: utf-8 -*-
"""把 content/ 打成可发布的远端内容包。

做三件事，顺序不能换：

1. **自检** —— 素材在不在、每个动作能不能求值、状态引用的帧有没有定义。
   这一步和程序侧的 `ContentPack.validate()` 是同一份代码，所以"发布时通过"
   就等于"客户端那边也会通过"。
2. **递增 content_version** —— 不递增客户端就认为没更新，压根不会去下。
3. **重算 SHA256 并生成 manifest.json** —— 客户端拿它对每个下载的文件做校验。

推送（传到 GitHub）不在这里做，交给 ``github-network-channels`` 技能里的
``gh_publish.py``：本机代理挑域名、Git Data API、Release 附件名非 ASCII 被替换
这些坑它都处理过了，没必要重造。本脚本跑完会打印下一步命令。

用法：
    python tools/publish_content.py            # 自检 + 递增版本 + 生成清单
    python tools/publish_content.py --no-bump  # 自检 + 生成清单（首次发布用，不动版本号）
    python tools/publish_content.py --check    # 只自检，什么都不改
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import contentpack  # noqa: E402

CONTENT_DIR = os.path.join(ROOT, "content")
ACTIONS = os.path.join(CONTENT_DIR, "actions.json")
MANIFEST = os.path.join(CONTENT_DIR, "manifest.json")

# 和 updater._safe_relpath 的白名单保持一致：更新器只认这两类扩展名，
# 发布侧多放了也传不过去，不如在打包时就发现。
ALLOWED = (".json", ".webp")

APP_MIN = "1.1.0"          # 带自动更新能力的第一版


def collect_files(content_dir):
    """列出要发布的文件（相对路径）。manifest.json 自己不进自己的清单。"""
    out = []
    for base, dirs, files in os.walk(content_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if not name.lower().endswith(ALLOWED):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, content_dir).replace("\\", "/")
            if rel == "manifest.json":
                continue
            out.append(rel)
    return sorted(out)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_actions():
    with open(ACTIONS, encoding="utf-8") as f:
        return json.load(f)


def save_actions(data):
    # newline="\n" **不能省**：Windows 上文本模式默认把 \n 写成 \r\n，
    # 而 .gitattributes 的 `* text=auto` 会在 git add 时把 CRLF 规范化回 LF。
    # 于是"本地算哈希的那份"和"远端实际下发的那份"就不是同一串字节，
    # 客户端的 SHA256 校验必然不过。下面 check_eol() 还会再拦一道。
    with open(ACTIONS, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def check_eol(files):
    """发布的 .json 必须是 LF 行尾 —— 这是客户端校验能否通过的前提。

    为什么这是硬约束而不是风格问题：``.gitattributes`` 里 `* text=auto`
    会在 ``git add`` 时把 CRLF 规范化成 LF，**远端拿到的永远是 LF**；
    而清单里的 SHA256 是拿本地文件算的。本地一旦是 CRLF，清单记的就是 CRLF 的哈希，
    客户端下回 LF 字节一比对必然不符，`updater` 判"校验不通过"→ 整包丢弃。
    Windows 上 Python 文本模式默认就写 CRLF，离踩这个坑只差一次带 `--bump` 的发布。
    所以把它做成**发布期就失败**，而不是上线后某天在用户那边静默失效。
    """
    bad = []
    for rel in files:
        if not rel.lower().endswith(".json"):
            continue
        path = os.path.join(CONTENT_DIR, *rel.split("/"))
        with open(path, "rb") as f:
            if b"\r" in f.read():
                bad.append(rel)
    return bad


def validate(data):
    """自检，分两层，缺一不可。

    第一层复用程序侧的 ``ContentPack.validate()``，按**客户端的解析顺序**来
    （先 content/ 再 assets/）—— 发布时通过就等于客户端那边也会通过。

    但光有第一层不够：新增素材如果忘了放进 ``content/pet/``，而 ``assets/pet/``
    里恰好有同名文件（覆盖内置动作时很常见），第一层会放它过去，客户端却拿不到。
    第二层专门堵这个：**新增的素材必须真的在 content/ 里**。
    """
    problems = []

    pack = contentpack.ContentPack(
        data.get("assets") or {}, data.get("motions") or {},
        data.get("states") or {}, [CONTENT_DIR, os.path.join(ROOT, "assets")])
    problems.extend(pack.validate())

    builtin_names = set()
    builtin_file = os.path.join(ROOT, "content", "actions.json")
    try:
        with open(builtin_file, encoding="utf-8") as f:
            builtin_names = set((json.load(f).get("assets") or {}).keys())
    except Exception:
        pass

    for name, meta in (data.get("assets") or {}).items():
        rel = str(meta.get("file") or "").replace("\\", "/")
        if not rel:
            problems.append(f"素材 {name} 没有 file 字段")
            continue
        shipped = os.path.isfile(os.path.join(CONTENT_DIR, *rel.split("/")))
        if not shipped and name not in builtin_names:
            problems.append(f"新增素材 {name} 的文件不在 content/ 里（{rel}），"
                            f"客户端拿不到")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只自检，不改任何文件")
    ap.add_argument("--no-bump", action="store_true",
                    help="生成清单但不递增版本号（首次把远端立起来时用）")
    args = ap.parse_args()

    if not os.path.isfile(ACTIONS):
        print(f"找不到 {ACTIONS}")
        return 2

    data = load_actions()
    old_ver = int(data.get("content_version", 0) or 0)

    print(f"[1] 自检 content/")
    problems = validate(data)
    if problems:
        print("  FAIL 内容包不合格，已中止（不会递增版本、不会生成清单）")
        for p in problems:
            print("       -", p)
        return 1
    n_states = len(data.get("states") or {})
    n_assets = len(data.get("assets") or {})
    n_motions = len(data.get("motions") or {})
    print(f"  OK   状态 {n_states} · 素材 {n_assets} · 动作 {n_motions}")
    print(f"  OK   无未定义素材、无求值失败的动效")

    files = collect_files(CONTENT_DIR)
    print(f"[2] 待发布文件 {len(files)} 个")
    total = 0
    for rel in files:
        size = os.path.getsize(os.path.join(CONTENT_DIR, *rel.split("/")))
        total += size
        print(f"       {size / 1024:8.1f} KB  {rel}")
    print(f"     合计 {total / 1024:.0f} KB")

    # 行尾检查必须排在递增版本号**之前**：不一致就整包作废，别留下"版本号涨了、
    # 清单没更新"的半成品状态。
    bad_eol = check_eol(files)
    if bad_eol:
        print("  FAIL 以下文件是 CRLF 行尾：")
        for rel in bad_eol:
            print("       -", rel)
        print("       git 的 `* text=auto` 会把远端存成 LF，清单却记的是本地 CRLF 的")
        print("       哈希 -> 客户端下回来一比对就不符，整包被丢弃。已中止。")
        print("       修法：把这些文件另存为 LF 行尾后重跑（本工具的 --bump 会以 LF 重写）。")
        return 1
    print("  OK   行尾均为 LF（与远端规范化结果一致，哈希可比）")

    if args.check:
        print(f"\n[i] --check 模式：版本仍为 r{old_ver}，未写任何文件")
        return 0

    new_ver = old_ver if args.no_bump else old_ver + 1
    if args.no_bump:
        print(f"[3] 版本保持 r{old_ver}（--no-bump）")
    else:
        data["content_version"] = new_ver
        save_actions(data)
        print(f"[3] 版本 r{old_ver} -> r{new_ver}")

    manifest = {
        "content_version": new_ver,
        "app_min": APP_MIN,
        "files": {},
    }
    if data.get("announce"):
        manifest["announce"] = data["announce"]
    # 注意顺序：哈希必须在 save_actions() 之后算。先算哈希再改版本号，
    # 清单里记的就是旧内容，客户端下回来一个都校验不过。
    for rel in files:
        path = os.path.join(CONTENT_DIR, *rel.split("/"))
        manifest["files"][rel] = {
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        }
    if "actions.json" not in manifest["files"]:
        print("  FAIL 文件表里没有 actions.json —— 客户端不会认为这是一次有效更新")
        return 1

    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  OK   已写出 {os.path.relpath(MANIFEST, ROOT)}（{len(manifest['files'])} 个文件）")

    print()
    print("下一步 —— 把 content/ 推送到仓库（走 GitHub REST API，本机 git push 受代理影响）：")
    print("    用 github-network-channels 技能里的 gh_publish.py push")
    print()
    print("推送后远端就绪，客户端下次启动会自动取到 r%d。" % new_ver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
