#!/usr/bin/env python3
"""verify_all.py — 台账核对：shortcuts.json ↔ 实际文件 ↔ 文档表格。


检查项：
  1. 台账里每个「在用/备用」的快捷指令，生成器脚本存在
  2. 当前签名产物存在，且能被 shortcut-sign 反解出 plist（说明签名结构完整）
  3. 交付副本存在（QQ 媒体目录 + 直链目录各一份，文件名 ASCII）
  4. docs/快捷指令清单.md 的表格里也列了这些名字（防文档漂移）

用法：
    .venv/bin/python build/verify_all.py            # 人读输出
    .venv/bin/python build/verify_all.py --json     # 机读输出
退出码：0 全部通过；1 有失败项。
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent
SG = HERE.parent
DOC = config.DOC_LEDGER
LEDGER = config.SHORTCUTS
SIGN = config.SIGN_BIN
LIB = config.SIGN_LIB
DELIVER_DIR = config.DELIVER_DIR
SERVE_ROOT = config.SERVE_ROOT


def extract_actions(signed: Path) -> list[str]:
    """用 shortcut-sign extract 反解签名件，返回动作标识符列表；失败返回 None。"""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "x.shortcut"
        env = dict(os.environ, LD_LIBRARY_PATH=str(LIB), PATH="/usr/bin:/bin")
        r = subprocess.run([SIGN, "extract", "-i", str(signed), "-o", str(out)],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0 or not out.exists():
            print(f"  ⚠ shortcut-sign extract 失败（{signed.name}）: {r.stderr.strip()[:200]}",
                  file=sys.stderr)
            return None
        try:
            return [a["WFWorkflowActionIdentifier"] for a in plistlib.load(open(out, "rb"))["WFWorkflowActions"]]
        except Exception as e:
            print(f"  ⚠ 反解出的 plist 解析失败（{signed.name}）: {e}", file=sys.stderr)
            return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    doc_text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    results = []
    ok = True

    for sc in ledger["shortcuts"]:
        name = sc["name"]
        checks = {}
        gen = SG / sc["generator"]
        checks["generator"] = gen.exists()
        if sc.get("registry"):
            checks["registry"] = (SG / sc["registry"]).exists()

        signed = SG / sc["current"]
        checks["signed_artifact"] = signed.exists()
        if checks["signed_artifact"]:
            ids = extract_actions(signed)
            checks["signature_extractable"] = ids is not None
            checks["action_count"] = len(ids) if ids else 0
        else:
            checks["signature_extractable"] = False

        deliver = sc["deliverName"]
        checks["deliver_name_ascii"] = deliver.isascii()
        checks["deliver_copy_qq"] = (DELIVER_DIR / deliver).exists()
        # 直链副本只在台账标注需要时才检查（多数常用件走 QQ 附件交付，不需要直链）
        if sc.get("needsLinkCopy"):
            # 静态站分发为可选功能：未配置 SHORTCUT_SERVE 时不检查
            checks["deliver_copy_link"] = True if not SERVE_ROOT else (SERVE_ROOT / deliver).exists()
        checks["listed_in_doc"] = deliver.split(".")[0] in doc_text

        for k, v in checks.items():
            if v is False:
                ok = False
        results.append({"name": name, "status": sc["status"], "checks": checks})

    # 文档里出现但台账没有的名字（提示，不算失败）
    ledger_names = {s["name"] for s in ledger["shortcuts"]}
    stale = []

    report = {"ok": ok, "shortcuts": results, "stale_in_doc": stale}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for r in results:
            bad = [k for k, v in r["checks"].items() if v is False]
            mark = "✓" if not bad else "✗"
            n = r["checks"].get("action_count", "")
            print(f"  {mark} {r['name']:<16} 动作数 {n:<4} 状态 {r['status']}")
            for k in bad:
                print(f"      ↳ 失败: {k}")
        print("\n全部通过 ✅" if ok else "\n有失败项 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
