#!/usr/bin/env python3
"""verify_struct.py — 用 vendor/shortcut_cli.py 做构建期结构门禁。

检查项：
1. canonical：UUID / GroupingIdentifier 必须在 WFWorkflowActionParameters 内
   （否则新版 iOS 导入器会静默裁切控制流块）
2. 动作数 > 0
3. 控制流配对：conditional/repeat 的开(mode=0) 与 关(mode=2) 数量一致

用法：
    .venv/bin/python build/verify_struct.py out/ShortcutPull.shortcut
    .venv/bin/python build/verify_struct.py --pretty out/ShortcutPull.shortcut
退出码：0 通过 / 1 不通过
"""
from __future__ import annotations

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SG = HERE.parent
CLI = SG / "vendor" / "shortcut_cli.py"

CONTROL_FLOW = {
    "is.workflow.actions.conditional",
    "is.workflow.actions.repeat.count",
    "is.workflow.actions.repeat.each",
    "is.workflow.actions.choosefrommenu",
}


def check(path: Path) -> tuple[bool, list[str]]:
    doc = plistlib.load(open(path, "rb"))
    acts = doc.get("WFWorkflowActions", [])
    msgs: list[str] = []
    ok = True

    if not acts:
        return False, ["动作数为 0"]

    bad_uuid = [i for i, a in enumerate(acts) if "UUID" in a]
    bad_gi = [i for i, a in enumerate(acts) if "GroupingIdentifier" in a]
    if bad_uuid:
        ok = False
        msgs.append(f"UUID 落在 action 顶层：{bad_uuid[:10]}（会被导入器裁切）")
    if bad_gi:
        ok = False
        msgs.append(f"GroupingIdentifier 落在 action 顶层：{bad_gi[:10]}")
    if ok:
        msgs.append(f"canonical OK（{len(acts)} 动作）")

    opens = closes = 0
    for a in acts:
        if a["WFWorkflowActionIdentifier"] not in CONTROL_FLOW:
            continue
        mode = a.get("WFWorkflowActionParameters", {}).get("WFControlFlowMode")
        if mode == 0:
            opens += 1
        elif mode == 2:
            closes += 1
    if opens != closes:
        ok = False
        msgs.append(f"控制流不配对：开 {opens} / 关 {closes}")
    else:
        msgs.append(f"控制流配对 OK（{opens} 开 / {closes} 关）")

    return ok, msgs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--pretty", action="store_true", help="额外打印可读控制流视图")
    args = ap.parse_args(argv)

    path = Path(args.file)
    ok, msgs = check(path)
    for m in msgs:
        print(("  ✓ " if ok else "  ✗ ") + m)

    if args.pretty and CLI.exists():
        r = subprocess.run(
            [sys.executable, str(CLI), "decompile", str(path), "--pretty"],
            capture_output=True, text=True, env={"SHORTCUT_CLI_LANG": "zh", "PATH": "/usr/bin:/bin"},
        )
        if r.returncode == 0:
            print(r.stdout)
        else:
            print("  ⚠ decompile --pretty 失败:", r.stderr[:400])

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
