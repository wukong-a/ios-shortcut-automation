#!/usr/bin/env python3
"""sync_server.py — 把 actions.json 里的 server 规格**单向**生成进 taskqueue 的 ACTIONS。


单一真相源方向：actions.json  →  build_pull.py（快捷指令分支）
                              →  sync_server.py（服务端校验）
禁止反向手改 server.mjs 的 ACTIONS：改了会被下一次同步覆盖，--check 会先报漂移。

用法：
    .venv/bin/python build/sync_server.py --check        # 只检查是否已同步（不改文件）
    .venv/bin/python build/sync_server.py --dry-run      # 打印将要写入的片段
    .venv/bin/python build/sync_server.py                # 写入（先备份 + node --check + 重启）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent
SG = HERE.parent
REGISTRY = config.REGISTRY
# server.mjs 位置：环境变量可覆盖（禁硬编码）
SERVER = config.SERVER_MJS

BEGIN = "// >>> GENERATED FROM tools/shortcutgen/build/actions.json — DO NOT EDIT BY HAND <<<"
END = "// <<< GENERATED FROM actions.json >>>"

# 需要按顺序排在前面的基础动作（保持与历史 diff 可比）
SPEC_KEYS = ("type", "required", "min", "max", "iso", "whitelistShortcuts")


def js_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def js_spec(spec: dict) -> str:
    body = ", ".join(f'{k}: {js_value(spec[k])}' for k in SPEC_KEYS if k in spec)
    return "{ " + body + " }"


def render_actions(manifest: dict) -> str:
    lines = ["const ACTIONS = {", "  " + BEGIN]
    for a in manifest["actions"]:
        srv = a.get("server", {})
        params = srv.get("params", {}) or {}
        head = ""
        if srv.get("requiresIdempotencyKey"):
            head = "requiresIdempotencyKey: true, "
        if not params:
            lines.append(f'  {json.dumps(a["action"])}: {{ {head}params: {{}} }},')
            continue
        lines.append(f'  {json.dumps(a["action"])}: {{ {head}params: {{')
        for pname, pspec in params.items():
            lines.append(f'    {pname}: {js_spec(pspec)},')
        lines.append("  } },")
    lines.append("  " + END)
    lines.append("};")
    return "\n".join(lines)


def replace_block(src: str, block: str) -> tuple[str, bool]:
    """把 server.mjs 里的 ACTIONS 块替换成生成的块；老文件（无标记）也能就地升级。"""
    if BEGIN in src:
        head = src[: src.index("const ACTIONS = {")]
        tail_at = src.find(END)
        if tail_at == -1:
            return src, False
        tail = src[tail_at + len(END):]
        tail = tail[tail.index("};") + 2:] if "};" in tail else tail
        return head + block + tail, True

    plain = re.compile(r"const ACTIONS = \{.*?\n\};", re.DOTALL)
    if plain.search(src):
        return plain.sub(lambda _: block, src, count=1), True
    return src, False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(REGISTRY))
    ap.add_argument("--server", default=str(SERVER))
    ap.add_argument("--check", action="store_true", help="只检查漂移（退出码 1 = 有漂移）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    server_path = Path(args.server)
    src = server_path.read_text(encoding="utf-8")
    block = render_actions(manifest)
    new_src, ok = replace_block(src, block)
    if not ok:
        print(f"✗ 在 {server_path} 里找不到 `const ACTIONS = {{ ... }};` 块", file=sys.stderr)
        return 2

    in_sync = new_src == src
    if args.dry_run:
        print(block)
        return 0
    if args.check:
        if in_sync:
            print(f"✓ {server_path} 与 actions.json 已同步（{len(manifest['actions'])} 个动作）")
            return 0
        print(f"✗ 漂移：{server_path} 的 ACTIONS 与 actions.json 不一致", file=sys.stderr)
        # 打印差异摘要
        old = re.search(r"const ACTIONS = \{(.*?)\n\};", src, re.DOTALL)
        new = re.search(r"const ACTIONS = \{(.*?)\n\};", new_src, re.DOTALL)
        old_names = re.findall(r'^\s*"([^"]+)":', old.group(1), re.MULTILINE) if old else []
        new_names = re.findall(r'^\s*"([^"]+)":', new.group(1), re.MULTILINE) if new else []
        only_old = [n for n in old_names if n not in new_names]
        only_new = [n for n in new_names if n not in old_names]
        if only_old:
            print("  仅在服务端:", only_old, file=sys.stderr)
        if only_new:
            print("  仅注册表:", only_new, file=sys.stderr)
        if not only_old and not only_new:
            print("  动作集合相同，但参数规格有差异", file=sys.stderr)
        return 1

    # 真写：备份 → 写临时 → node --check → 落盘 → 重启
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = server_path.with_suffix(server_path.suffix + f".bak.{stamp}")
    shutil.copy2(server_path, backup)
    tmp = server_path.with_suffix(server_path.suffix + ".new")
    tmp.write_text(new_src, encoding="utf-8")

    chk = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
    if chk.returncode != 0:
        tmp.unlink(missing_ok=True)
        print("✗ 生成的 ACTIONS 语法不过 node --check，已放弃写入：", file=sys.stderr)
        print(chk.stderr, file=sys.stderr)
        return 3
    shutil.move(str(tmp), str(server_path))
    print(f"✓ 已同步 {len(manifest['actions'])} 个动作 → {server_path}（备份 {backup.name}）")

    if not args.no_restart:
        r = subprocess.run(["systemctl", "restart", config.SERVICE_NAME], capture_output=True, text=True)
        print(f"  systemctl restart {config.SERVICE_NAME}:", "ok" if r.returncode == 0 else r.stderr.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
