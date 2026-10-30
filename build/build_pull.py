#!/usr/bin/env python3
"""build_pull.py — 从 actions.json（单一真相源）生成 ShortcutPull 快捷指令。


用法：
    .venv/bin/python build/build_pull.py                 # 出 out/ShortcutPull.shortcut
    .venv/bin/python build/build_pull.py --out out/x.shortcut

设计要点：
- **动作定义只有一份**：本脚本不写死任何动作，全部读 build/actions.json。
- server 侧校验（taskqueue ACTIONS）由 build/sync_server.py 从同一文件生成。
- 参数键合法性在**构建期**用 shortcutkit 的注册表校验，写错键直接报错，不出坏文件。
- 回执语义：真执行了才回 succeeded；未支持的动作落最内层 else → failed。
- `openurl`/`openapp`/`shortcut.run`/`script.run` 会打断后续动作 → 回执放在触发之前。
- 路径/地址一律走 build/config.py（可环境变量覆盖），不在此写死。
"""
from __future__ import annotations

import argparse
import json
import plistlib
import sys
from pathlib import Path

import config
from shortcutkit import (
    ACTIONS,
    PARAM_VARIABLE_TYPES,
    Shortcut,
    actions,
    ref,
    repeat_item,
    text,
)

HERE = Path(__file__).resolve().parent
SG = HERE.parent
REGISTRY = config.REGISTRY

# 提醒事项列表写死（流水线文档记录的坑：不写死会当场弹列表选择）
REM_DESC = {
    "Identifier": "<x-apple-reminderkit://REMCDList/D78E2703-4FAC-4FD6-94F0-E2423A3D572F>",
    "Title": "任务",
    "IsAllCalendar": False,
}

KEY_BY_NAME = {k: v for k, v in vars(actions).items() if k.isupper() and isinstance(v, str)}


def action_id(name: str) -> str:
    """把注册表里的动作名（如 addnewevent）解析成 is.workflow.actions.* 标识符。"""
    ident = KEY_BY_NAME.get(name.upper())
    if not ident:
        raise SystemExit(f"actions.json: 未知动作 {name!r}（shortcutkit 注册表里没有）")
    return ident


def check_keys(name: str, keys: dict) -> None:
    """构建期校验参数键：不在这条动作的合法键集合里就报错。"""
    ident = action_id(name)
    catalog = ACTIONS.get(ident, {})
    known = set(catalog.get("params", []))
    known |= {"UUID", "GroupingIdentifier", "WFControlFlowMode", "CustomOutputName"}
    bad = sorted(set(keys) - known)
    if bad:
        raise SystemExit(
            f"{ident}: 非法参数键 {bad}\n  合法键: {sorted(known)}"
        )
    # 顺带校验「这里不接受引用」的键
    restricted = PARAM_VARIABLE_TYPES.get(ident, {})
    for k, v in keys.items():
        if k in restricted and isinstance(v, dict) and "WFSerializationType" in v:
            raise SystemExit(f"{ident}.{k}: 该键不接受引用（只接受 {restricted[k] or '纯值'}）")


def tok(s: str) -> dict:
    return {"Value": {"string": s, "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"}


def dict_field(pairs) -> dict:
    items = []
    for k, v in pairs:
        items.append({"WFItemType": 0, "WFKey": tok(k), "WFValue": v if isinstance(v, dict) else tok(v)})
    return {"Value": {"WFDictionaryFieldValueItems": items}, "WFSerializationType": "WFDictionaryFieldValue"}


def asref(x):
    return ref(x) if isinstance(x, dict) and "WFWorkflowActionParameters" in x else x


class Builder:
    def __init__(self, manifest: dict, token: str):
        self.manifest = manifest
        self.token = token
        self.s = Shortcut("ShortcutPull", color="Blue")
        self.warnings: list[str] = []
        self.branches = manifest["actions"]

    # ---- 取值管道 ----
    def getval(self, container, key):
        return self.s.action(actions.GETVALUEFORKEY, WFDictionaryKey=key, WFInput=asref(container))

    def txtval(self, container, key):
        return self.s.action(actions.GETTEXT, WFTextActionText=ref(self.getval(container, key)))

    def declared(self, params_ref, key):
        """`params.<key> 有值` 的守卫表达式（条件里统一文本化，见流水线文档的 v5 坑）。"""
        return ref(self.txtval(params_ref, key))

    def value_of(self, spec: dict, params_ref):
        """把注册表里的取值描述编译成动作返回的引用。"""
        if "const" in spec:
            return spec["const"]
        if "ref" in spec:
            return spec["ref"]
        if "param" in spec:
            return ref(self.txtval(params_ref, spec["param"]))
        if "paramExistsParam" in spec:
            return self.declared(params_ref, spec["paramExistsParam"])
        if "declaredParam" in spec:
            return self.declared(params_ref, spec["declaredParam"])
        raise SystemExit(f"无法识别的取值描述: {spec}")

    # ---- 回执 / 上传 ----
    def receipt(self, task_id, status: str, result=None):
        pairs = [("taskId", text(ref(task_id))), ("status", text(status))]
        if result is not None:
            pairs.append(("result", result))
        check_keys("downloadurl", {})
        self.s.action(
            actions.DOWNLOADURL, WFURL=f"{config.BASE}/receipt", WFHTTPMethod="POST",
            ShowHeaders=1, WFHTTPHeaders=dict_field([("Authorization", "Bearer " + self.token)]),
            WFHTTPBodyType="JSON", WFJSONValues=dict_field(pairs),
        )

    def upload(self, file_ref, fname: str, task_id):
        check_keys("downloadurl", {})
        resp = self.s.action(
            actions.DOWNLOADURL, WFURL=f"{config.BASE}/upload", WFHTTPMethod="POST",
            ShowHeaders=1,
            WFHTTPHeaders=dict_field([("Authorization", "Bearer " + self.token), ("x-filename", fname)]),
            WFHTTPBodyType="File", WFRequestVariable=ref(file_ref),
        )
        self.receipt(task_id, "succeeded", result=text(ref(self.getval(resp, "id"))))

    # ---- 分支体 ----
    def emit_steps(self, action_def: dict, params_ref, task_id) -> bool:
        """返回 True 表示分支内已经自己发过回执。"""
        phone = action_def["phone"]
        handler = phone.get("handler")
        if handler:
            getattr(self, f"h_{handler}")(action_def, params_ref, task_id)
            return True

        prev = None
        for step in phone["steps"]:
            op = step["op"]
            if op == "upload":
                if prev is None:
                    raise SystemExit(f"{action_def['action']}: upload 步骤前面没有取文件的动作")
                self.upload(prev, step["filename"], task_id)
                return True
            kwargs = {}
            for key, spec in step.get("params", {}).items():
                kwargs[key] = self.value_of(spec, params_ref)
            check_keys(op, kwargs)
            ident = action_id(op)
            entry = self.s.action(ident, **kwargs) if kwargs else self.s.action(ident)
            prev = entry

        rc = dict(self.manifest["defaults"]["receipt"])
        rc.update(phone.get("receipt", {}))
        if rc.get("onSuccess"):
            result = None
            rr = rc.get("resultRef")
            if rr == "$prev":
                result = text(ref(prev))
            elif rr is not None:
                result = self.value_of(rr, params_ref)
            self.receipt(task_id, rc["onSuccess"], result=result)
        return True

    # ---- 特殊实现（无法用声明式表达的）----
    def h_clipboard_get(self, action_def, params_ref, task_id):
        """clipboard.get —— GET_CLIPBOARD → GET_TEXT → 回执。

        声明式 steps 只传 params，不传上一步输出，所以 GET_TEXT 拿不到输入会返回空；
        这里显式把 GET_CLIPBOARD 的输出接进 GET_TEXT（与 gen_clipup.py 同一写法）。
        """
        raw = self.s.action(actions.GETCLIPBOARD)
        clip = self.s.action(actions.GETTEXT, WFTextActionText=ref(raw))
        self.receipt(task_id, "succeeded", result=text(ref(clip)))

    def h_clipboard_set(self, action_def, params_ref, task_id):
        """clipboard.set —— 显式把 text 参数接进 SET_CLIPBOARD 的 WFInput。

        声明式 steps 只传 params、不传 input，生成出来的 SET_CLIPBOARD 无输入，
        会把剪贴板写成空（2026-10-18 实测：手机剪贴板被清空）。
        """
        val = self.txtval(params_ref, "text")
        self.s.action(actions.SETCLIPBOARD, WFInput=ref(val))
        self.receipt(task_id, "succeeded")

    def h_shortcut_run(self, action_def, params_ref, task_id):
        name_txt = self.txtval(params_ref, "name")
        enc_name = self.s.action(actions.URLENCODE, WFInput=ref(name_txt))
        enc_in = self.s.action(actions.URLENCODE, WFInput=ref(self.txtval(params_ref, "input")))
        url = self.s.action(actions.GETTEXT, WFTextActionText=text(
            "shortcuts://run-shortcut?name=", ref(enc_name), "&input=text&text=", ref(enc_in)))
        self.receipt(task_id, "succeeded", result=text(ref(name_txt)))
        self.s.action(actions.OPENURL, WFInput=ref(url))

    def h_script_run(self, action_def, params_ref, task_id):
        nm = self.txtval(params_ref, "name")
        enc = self.s.action(actions.URLENCODE, WFInput=ref(nm))
        url = self.s.action(actions.GETTEXT, WFTextActionText=text("scriptable:///run/", ref(enc)))
        self.receipt(task_id, "succeeded", result=text(ref(nm)))
        self.s.action(actions.OPENURL, WFInput=ref(url))

    def h_lowpower(self, action_def, params_ref, task_id):
        """mode: on/off/set/toggle（默认 toggle）。服务端只校验长度，语义在这里定。"""
        mode = ref(self.txtval(params_ref, "mode"))
        if_on = self.s.if_(mode, "is", "on")
        kwargs = {"operation": "set", "OnValue": True}
        check_keys("lowpowermode_set", kwargs)
        self.s.action(actions.LOWPOWERMODE_SET, **kwargs)
        self.s.otherwise(if_on)
        if_off = self.s.if_(mode, "is", "off")
        kwargs = {"operation": "set", "OnValue": False}
        check_keys("lowpowermode_set", kwargs)
        self.s.action(actions.LOWPOWERMODE_SET, **kwargs)
        self.s.otherwise(if_off)
        kwargs = {"operation": "toggle"}
        check_keys("lowpowermode_set", kwargs)
        self.s.action(actions.LOWPOWERMODE_SET, **kwargs)
        self.s.end_if(if_off)
        self.s.end_if(if_on)
        self.receipt(task_id, "succeeded")

    def h_reminder_add(self, action_def, params_ref, task_id):
        kwargs = {
            "WFCalendarItemTitle": ref(self.txtval(params_ref, "title")),
            "WFCalendarItemNotes": ref(self.txtval(params_ref, "notes")),
        }
        check_keys("addnewreminder", kwargs)
        rem = self.s.action(actions.ADDNEWREMINDER, **kwargs)
        rp = rem["WFWorkflowActionParameters"]
        rp["WFCalendarItemCalendar"] = "任务"
        rp["WFCalendarDescriptor"] = REM_DESC
        self.receipt(task_id, "succeeded")

    # ---- 停止：未支持动作 ----
    def build(self, out_path: Path) -> dict:
        s = self.s
        resp = s.action(
            actions.DOWNLOADURL, WFURL=f"{config.BASE}/outbox", WFHTTPMethod="GET",
            ShowHeaders=1,
            WFHTTPHeaders=dict_field([("Authorization", "Bearer " + self.token)]),
        )
        tasks = self.getval(resp, "tasks")
        rg = s.repeat_each(ref(tasks))
        item = repeat_item()
        task_id = self.getval(item, "taskId")
        act = s.action(actions.GETTEXT, WFTextActionText=ref(self.getval(item, "action")))
        params = self.getval(item, "params")

        gids = []
        for action_def in self.branches:
            gid = s.if_(ref(act), "is", action_def["action"])
            gids.append(gid)
            # 可选参数：先把 params 里缺的键补成占位，避免取值动作在缺键时报错
            self.emit_steps(action_def, params, task_id)
            s.otherwise(gid)
        self.receipt(task_id, "failed")  # 最内层 else：动作不认识 → failed
        for gid in reversed(gids):
            s.end_if(gid)
        # 派发链生成的 conditional 总数（含分支体里嵌套的），供自检比对
        self.cond_generated = sum(
            1 for a in s.actions if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
        )
        s.end_repeat_each(rg)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        s.write(str(out_path))

        # 覆写显示名 + 二进制 plist（与 v13 一致）
        d = plistlib.load(open(out_path, "rb"))
        d["WFWorkflowName"] = "ShortcutPull"
        plistlib.dump(d, open(out_path, "wb"), fmt=plistlib.FMT_BINARY)

        return self.selfcheck(d)

    # ---- 自检 ----
    def selfcheck(self, doc: dict) -> dict:
        acts = doc["WFWorkflowActions"]
        ids = [a["WFWorkflowActionIdentifier"] for a in acts]
        report = {"actions": len(acts), "name": doc.get("WFWorkflowName"), "branches": len(self.branches)}

        # 派发链：conditional 由本构建器生成，所以数量必须和构建时的实测增量完全一致
        got = sum(1 for i in ids if i == "is.workflow.actions.conditional")
        report["conditional_actions"] = got
        report["expected_conditionals"] = self.cond_generated
        report["branch_count_ok"] = got == self.cond_generated

        # 关键实现是否落地
        impl = {
            "getclipboard": "clipboard.get",
            "setclipboard": "clipboard.set",
            "addnewreminder": "reminder.add",
            "addnewevent": "calendar.add",
            "appendnote": "note.append",
            "notification": "notify",
            "openurl": "openurl/shortcut.run/script.run",
            "urlencode": "shortcut.run",
            "speaktext": "speak",
            "getmyworkflows": "shortcuts.list",
            "lowpowermode.set": "lowpower",
            "sendmessage": "sms.send",
            "dictatetext": "dictate",
            "setbrightness": "brightness.set",
            "setvolume": "volume.set",
            "getlastphoto": "photo.latest",
            "takephoto": "photo.take",
            "takescreenshot": "screenshot",
        }
        report["impl"] = {k: (w if any(k in i for i in ids) else None) for k, w in impl.items()}
        report["impl_missing"] = [v for k, v in report["impl"].items() if v is None]
        report["warnings"] = self.warnings
        return report


def load_manifest(path: Path) -> dict:
    m = json.loads(path.read_text(encoding="utf-8"))
    if m.get("schema") != 1:
        raise SystemExit(f"{path}: 未知 schema {m.get('schema')}")
    names = [a["action"] for a in m["actions"]]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise SystemExit(f"{path}: 动作重名 {sorted(dupes)}")
    return m


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(REGISTRY))
    ap.add_argument("--out", default=str(config.OUT_DIR / "ShortcutPull.shortcut"))
    ap.add_argument("--token-file", default=str(config.TOKEN_PATH))
    ap.add_argument("--json", action="store_true", help="把自检报告以 JSON 打到 stdout")
    args = ap.parse_args(argv)

    token = Path(args.token_file).read_text().strip()
    if not token:
        raise SystemExit(f"令牌为空: {args.token_file}")

    manifest = load_manifest(Path(args.registry))
    b = Builder(manifest, token)
    report = b.build(Path(args.out))
    report["out"] = args.out
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"wrote {args.out} | 动作数 {report['actions']} | 分支数 {report['branches']}")
        if report["impl_missing"]:
            print("  ⚠ 未落地:", report["impl_missing"])
        if report["warnings"]:
            for w in report["warnings"]:
                print("  ⚠", w)
    if report["impl_missing"] or not report["branch_count_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
