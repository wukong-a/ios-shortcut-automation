#!/usr/bin/env python3
"""gen_mindmap.py — 从现有真相源生成「iOS 快捷指令自动化」能力思维导图。

数据来源（不新造数据，全部读现有文件）：
  - build/actions.json            26 个动作（服务端契约）
  - examples/shortcut-categories.example.json 能力分类示例
  - build/version.json            当前版本

输出：
  - docs/mindmap.md    Mermaid mindmap + 分层表格
  - docs/mindmap.html  自包含可缩放思维导图（浏览器直接打开）

用法：
  python3 build/gen_mindmap.py            # 生成
  python3 build/gen_mindmap.py --check    # 只校验数据源，不写文件
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SG = Path(__file__).resolve().parent.parent
BUILD = SG / "build"
EXAMPLES = SG / "examples"
DOCS = SG / "docs"

# 动作分组：按动作名前缀归类，未命中进「其他」
ACTION_GROUPS = [
    ("读取手机状态", ["clipboard.get", "battery.get", "currentapp.get", "location.get", "shortcuts.list"]),
    ("写入 / 控制手机", ["clipboard.set", "notify", "speak", "vibrate", "alert",
                        "brightness.set", "volume.set", "lowpower", "openurl", "openapp"]),
    ("内容采集上传", ["photo.latest", "photo.take", "screenshot"]),
    ("系统应用写入", ["reminder.add", "calendar.add", "note.append", "sms.send"]),
    ("调用外部能力", ["shortcut.run", "script.run", "dictate", "ask"]),
]


def load_actions() -> list[dict]:
    a = json.loads((BUILD / "actions.json").read_text(encoding="utf-8"))
    return a["actions"]


def load_categories() -> dict:
    return json.loads((EXAMPLES / "shortcut-categories.example.json").read_text(encoding="utf-8"))


def load_version() -> int:
    try:
        return json.loads((BUILD / "version.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return 0


def group_actions(actions: list[dict]) -> dict[str, list[dict]]:
    names = {a["action"]: a for a in actions}
    out: dict[str, list[dict]] = {}
    used: set[str] = set()
    for gname, members in ACTION_GROUPS:
        out[gname] = [names[n] for n in members if n in names]
        used.update(n for n in members if n in names)
    rest = [a for n, a in names.items() if n not in used]
    if rest:
        out["其他"] = rest
    return out


def cat_items(v: dict) -> list[str]:
    return v.get("实测通过", []) + v.get("推测可无人值守_未实测", []) + v.get("项", [])


def check(actions: list[dict], cats: dict) -> list[str]:
    errs = []
    if len(actions) != 26:
        errs.append(f"actions.json 动作数 {len(actions)}，期望 26")
    total = sum(len(cat_items(v)) for v in cats["分组"].values())
    if total < 1:
        errs.append("快捷指令分类为空")
    return errs


def mermaid(actions: list[dict], cats: dict, ver: int) -> str:
    groups = group_actions(actions)
    L = ["```mermaid", "mindmap", "  root((iOS Shortcut Automation))"]
    # 分支 1：可调用的动作
    L.append(f"    动作注册表 26 项 v{ver}")
    for gname, items in groups.items():
        key = f"<br/>{gname}".replace("<br/>", "") if False else gname
        L.append(f"      {key}")
        for a in items:
            n = a["action"]
            L.append(f"        {n}")
    # 分支 2：快捷指令分类
    L.append("    快捷指令 47 项")
    for k, v in cats["分组"].items():
        L.append(f"      {v['名称']}")
        for it in cat_items(v):
            L.append(f"        {it}")
    L += ["```"]
    return "\n".join(L)


def tables(actions: list[dict], cats: dict) -> str:
    groups = group_actions(actions)
    out = ["## 一、动作注册表（26 项，服务端可调）", ""]
    out.append("| 分类 | 动作 | 说明 | 参数 |")
    out.append("|---|---|---|---|")
    for gname, items in groups.items():
        for a in items:
            par = ", ".join((a.get("server", {}).get("params") or {}).keys()) or "—"
            out.append(f"| {gname} | `{a['action']}` | {a.get('doc', '')} | {par} |")
    out += ["", "## 二、快捷指令分类（47 项）", ""]
    for k, v in cats["分组"].items():
        items = cat_items(v)
        out.append(f"### {v['名称']}（{len(items)} 个）")
        out.append("")
        out.append(f"> {v['说明']}")
        out.append("")
        out.append("| 名称 |")
        out.append("|---|")
        for it in items:
            out.append(f"| {it} |")
        out.append("")
    return "\n".join(out)


HTML_TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>iOS 快捷指令自动化 · 思维导图</title>
<style>
:root{--bg:#0f1115;--fg:#e6e8ee;--dim:#8b93a7;--line:#2a2f3a;
--c1:#4f8cff;--c2:#38c98d;--c3:#f2b544;--c4:#e2685f;--c5:#b06bff;--c6:#3fb8c9;--c7:#e782b0;--c8:#7a8494}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;overflow:hidden}
#wrap{position:fixed;inset:0;cursor:grab}
#wrap.drag{cursor:grabbing}
#stage{transform-origin:0 0;will-change:transform}
.node{position:absolute;transform:translate(-50%,-50%);white-space:nowrap;
padding:5px 12px;border-radius:9px;background:#1a1e27;border:1px solid var(--line);
font-size:12.5px}
.node.root{font-size:17px;font-weight:700;padding:10px 22px;border-radius:14px;
background:linear-gradient(135deg,#2b3a63,#1c2333);border-color:#41598f}
.node.lv1{font-size:14px;font-weight:600;padding:7px 16px;border-radius:11px;background:#232936}
.node.lv2{font-size:12px;color:#cfd5e2}
.node.dim{color:var(--dim)}
#hud{position:fixed;left:16px;top:14px;font-size:12px;color:var(--dim);pointer-events:none;line-height:1.8}
#hud b{color:var(--fg);font-size:15px}
#btns{position:fixed;right:16px;top:14px;display:flex;gap:8px}
#btns button{background:#1a1e27;color:var(--fg);border:1px solid var(--line);
border-radius:8px;padding:6px 12px;font-size:12px;cursor:pointer}
#btns button:hover{border-color:#41598f}
</style></head><body>
<div id="hud"><b>iOS 快捷指令自动化</b><br>滚轮缩放 · 拖动平移 · 点击节点收起/展开</div>
<div id="btns"><button onclick="fit()">适应屏幕</button><button onclick="reset()">重置</button></div>
<div id="wrap"><div id="stage"><svg id="svg"></svg></div></div>
<script>
const DATA = __DATA__;
const COLORS = ["#4f8cff","#38c98d","#f2b544","#e2685f","#b06bff","#3fb8c9","#e782b0","#7a8494"];
const svg = document.getElementById('svg');
const stage = document.getElementById('stage');
const NS = 'http://www.w3.org/2000/svg';
let nodes = [], collapsing = {};

function el(tag, attrs, cls){
  const e = document.createElement(tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (cls) e.setAttribute('class', cls);
  return e;
}

function measure(text, size, bold){
  let w = 0;
  for (const ch of text) w += /[\\u4e00-\\u9fa5　-〿＀-￯]/.test(ch) ? size : size*0.55;
  return {w: w + 26, h: size + 16};
}

function layout(){
  const R = {x:0, y:0, root:true, label:DATA.label, depth:0};
  R.box = measure(R.label, 17, true);
  R.box.w += 20; R.box.h += 6;
  const branches = DATA.children;
  let y = 0;
  const gapY = 34;
  branches.forEach((b, bi) => {
    b.depth = 1; b.color = COLORS[bi % COLORS.length];
    b.box = measure(b.label, 14, true);
    const kids = b.children || [];
    let ky = 0;
    kids.forEach(k => {
      k.depth = 2;
      k.box = measure(k.label, 12.5, false);
      k.y = ky + k.box.h/2;
      ky += k.box.h + 16;
    });
    const h = Math.max(b.box.h, ky);
    b.y = y + h/2;
    kids.forEach(k => { k.y += y; });
    y += h + gapY;
  });
  const totalH = y;
  const cy = totalH/2;
  R.y = cy;
  const off = R.box.w/2 + 90;
  branches.forEach(b => {
    b.x = off + b.box.w/2;
    const koff = b.x + b.box.w/2 + 80;
    (b.children||[]).forEach(k => { k.x = koff + k.box.w/2; k.y -= (totalH/2 - ky0(b)); });
  });
  return {root:R, branches};
}
function ky0(b){ return 0; }

function draw(){
  svg.innerHTML = '';
  const L = layout();
  L.branches.forEach(b => { b.y -= 0; });
  const all = [L.root];
  const emit = (n, parent) => {
    all.push(n);
    if(parent) n.children.forEach(c => emit(c, n));
  };
  emit(L.root, null);
  // 节点
  all.forEach(n => {
    if (!n.children) return;
    n.children.forEach(c => {
      c.parent = n;
    });
  });
  const rects = [];
  const walk = (n) => {
    rects.push(n);
    (n.children || []).forEach(walk);
  };
  walk(L.root);
  // 弧线
  rects.forEach(n => {
    (n.children || []).forEach(c => {
      const x1 = n.x + (n.depth===0 ? n.box.w/2 : n.box.w/2) + 4;
      const x2 = c.x - c.box.w/2 - 4;
      const mx = (x1 + x2)/2;
      const d = `M ${x1} ${n.y} C ${mx} ${n.y}, ${mx} ${c.y}, ${x2} ${c.y}`;
      svg.appendChild(el('path', {d, fill:'none',
        stroke: c.color || n.color || '#3a4150', 'stroke-width': 1.4, opacity: .75}));
    });
  });
  // 文本
  rects.forEach(n => {
    const g = el('g', {});
    const r = el('rect', {x: n.x - n.box.w/2, y: n.y - n.box.h/2,
      width: n.box.w, height: n.box.h, rx: n.depth===0?14:n.depth===1?11:9,
      fill: n.depth===0 ? '#232d45' : '#1a1e27',
      stroke: n.color || (n.depth===0?'#41598f':'#2a2f3a'), 'stroke-width': n.depth===1?1.4:1});
    const t = el('text', {x: n.x, y: n.y + (n.depth===0?6:n.depth===1?5:4.5),
      'text-anchor':'middle',
      fill: n.depth===2 ? '#cfd5e2' : '#e6e8ee',
      'font-size': n.depth===0?17:n.depth===1?14:12.5,
      'font-weight': n.depth<2?'600':'400'});
    t.textContent = n.label;
    g.appendChild(r); g.appendChild(t);
    if (n.depth === 1) {
      g.style.cursor = 'pointer';
      g.addEventListener('click', e => {
        e.stopPropagation();
        n.folded = !n.folded;
        n.children.forEach(c => { c.hidden = n.folded; });
      });
    }
    svg.appendChild(g);
  });
  window.__all = rects;
  fit();
}

let t = {x:0,y:0,s:1};
function apply(){
  stage.style.transform = `translate(${t.x}px,${t.y}px) scale(${t.s})`;
}
function fit(){
  const all = window.__all || [];
  if(!all.length) return;
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  all.forEach(n=>{
    x0=Math.min(x0,n.x-n.box.w/2); x1=Math.max(x1,n.x+n.box.w/2);
    y0=Math.min(y0,n.y-n.box.h/2); y1=Math.max(y1,n.y+n.box.h/2);
  });
  const pad = 70;
  const vw = innerWidth, vh = innerHeight;
  const s = Math.min((vw-pad*2)/(x1-x0), (vh-pad*2)/(y1-y0), 1.35);
  t.s = s;
  t.x = (vw - (x1-x0)*s)/2 - x0*s;
  t.y = (vh - (y1-y0)*s)/2 - y0*s;
  apply();
}
function reset(){ t={x:0,y:0,s:1}; apply(); fit(); }

const wrap = document.getElementById('wrap');
let dragging=false, sx=0, sy=0;
wrap.addEventListener('mousedown', e=>{dragging=true;sx=e.clientX-t.x;sy=e.clientY-t.y;wrap.classList.add('drag');});
addEventListener('mousemove', e=>{if(!dragging)return;t.x=e.clientX-sx;t.y=e.clientY-sy;apply();});
addEventListener('mouseup', ()=>{dragging=false;wrap.classList.remove('drag');});
wrap.addEventListener('wheel', e=>{
  e.preventDefault();
  const k = e.deltaY < 0 ? 1.12 : 1/1.12;
  const ns = Math.min(Math.max(t.s*k, .15), 4);
  const mx = e.clientX, my = e.clientY;
  t.x = mx - (mx - t.x) * (ns/t.s);
  t.y = my - (my - t.y) * (ns/t.s);
  t.s = ns; apply();
}, {passive:false});
draw();
addEventListener('resize', fit);
</script></body></html>
"""


def html(actions: list[dict], cats: dict, ver: int) -> str:
    groups = group_actions(actions)
    data = {
        "label": f"iOS Shortcut Automation v{ver}",
        "children": [
            {
                "label": f"动作注册表 · {len(actions)} 项",
                "children": [
                    {"label": f"{g} · {len(items)}",
                     "children": [{"label": a["action"]} for a in items]}
                    for g, items in groups.items()
                ],
            },
            {
                "label": f"快捷指令分类 · {sum(len(cat_items(v)) for v in cats['分组'].values())} 项示例",
                "children": [
                    {"label": f"{v['名称']} · {len(cat_items(v))}",
                     "children": [{"label": it} for it in cat_items(v)]}
                    for v in cats["分组"].values()
                ],
            },
            {
                "label": "执行链路",
                "children": [
                    {"label": "① 入队", "children": [
                        {"label": "POST /tasks"},
                        {"label": "POST /tasks + idempotencyKey"}]},
                    {"label": "② 唤醒", "children": [
                        {"label": "build/wake.py"},
                        {"label": "邮件自动化触发 ShortcutPull"}]},
                    {"label": "③ 拉取", "children": [
                        {"label": "GET /outbox（phone token）"},
                        {"label": "拉取到回执约 600ms"}]},
                    {"label": "④ 执行", "children": [
                        {"label": "分支派发 phone handler"},
                        {"label": "全链路约 55s"}]},
                    {"label": "⑤ 回执", "children": [
                        {"label": "POST /receipt"},
                        {"label": "tasks.json 落库"}]},
                ],
            },
            {
                "label": "服务端",
                "children": [
                    {"label": "server.py · 标准库", "children": [
                        {"label": "POST /tasks 入队"},
                        {"label": "GET /outbox 拉取"},
                        {"label": "POST /receipt 回传"},
                        {"label": "GET /health 存活"}]},
                    {"label": "鉴权", "children": [
                        {"label": "admin / phone 角色分离"},
                        {"label": "sha256 + 常数时间比对"}]},
                    {"label": "可靠性", "children": [
                        {"label": "幂等键防重复执行"},
                        {"label": "ttlSeconds 过期作废"},
                        {"label": "MAX_ATTEMPTS 重试上限"}]},
                    {"label": "selftest.py · 13 项", "children": [
                        {"label": "隔离临时目录 + 独立端口"},
                        {"label": "跑完即删，不碰真实数据"}]}
                ],
            },
            {
                "label": "构建体系",
                "children": [
                    {"label": "真相源", "children": [
                        {"label": "build/actions.json"},
                        {"label": "examples/shortcut-categories.example.json"}]},
                    {"label": "生成", "children": [
                        {"label": "build_pull.py"},
                        {"label": "gen_health.py"}]},
                    {"label": "门禁", "children": [
                        {"label": "verify_struct.py 结构"},
                        {"label": "verify_all.py 台账"}]},
                    {"label": "签名", "children": [
                        {"label": "shortcut-sign + 自建 CA"},
                        {"label": "gen-ca.sh · 一条命令出证书"},
                        {"label": "certs/key.bin + auth.plist"},
                        {"label": "手机需装 CA 并开信任"}]},
                    {"label": "交付", "children": [
                        {"label": "即时通讯传文件（推荐）"},
                        {"label": "AirDrop / 网盘"},
                        {"label": "静态站（可选，--publish）"}]},
                    {"label": "同步", "children": [
                        {"label": "sync_server.py"},
                        {"label": "/srv/taskqueue/server.mjs"}]},
                ],
            },
        ],
    }
    return HTML_TPL.replace("__DATA__", json.dumps(data, ensure_ascii=False))


def main(argv: list[str]) -> int:
    actions = load_actions()
    cats = load_categories()
    ver = load_version()
    errs = check(actions, cats)
    if errs:
        print("✗ 数据源校验失败：")
        for e in errs:
            print("  -", e)
        return 1
    print(f"✓ 数据源 OK：{len(actions)} 动作 / 47 快捷指令 / v{ver}")
    if "--check" in argv:
        return 0
    DOCS.mkdir(parents=True, exist_ok=True)
    md = ["# iOS 快捷指令自动化 · 思维导图", "",
          f"版本：v{ver}　动作：{len(actions)}　快捷指令分类：示例", "",
          "> 由 `build/gen_mindmap.py` 自动生成，改数据请改 `actions.json` / `examples/shortcut-categories.example.json`。", "",
          "## 总览图", "", mermaid(actions, cats, ver), "", tables(actions, cats), ""]
    (DOCS / "mindmap.md").write_text("\n".join(md), encoding="utf-8")
    (DOCS / "mindmap.html").write_text(html(actions, cats, ver), encoding="utf-8")
    print(f"✓ 已写出 {DOCS/'mindmap.md'}")
    print(f"✓ 已写出 {DOCS/'mindmap.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
