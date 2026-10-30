#!/usr/bin/env python3
"""server.py — 最小可跑的任务队列服务端（参考实现）。

这是 iOS 快捷指令自动化链路的**服务端那一半**：手机来拉任务、执行、回传结果。

设计目标：**看得懂、跑得起来、不改一行就能用**。
不追求生产级，追求「clone 下来 python3 server.py 就能测试」。

## 三个接口

    POST /tasks      入队任务（需 admin 令牌）
    GET  /outbox     手机拉取待执行任务（需 phone 令牌）
    POST /receipt    手机回传执行结果（需 phone 令牌）
    GET  /health     存活检查（无需鉴权）

## 鉴权

用一个 JSON 文件存令牌，每个令牌带角色：

    {"tokens": [{"token": "xxx", "roles": ["admin"]},
                {"token": "yyy", "roles": ["phone"]}]}

令牌比对用 sha256 + 常数时间比较，避免时序侧信道。

## 启动

    python3 server.py                     # 默认 0.0.0.0:8790
    PORT=9000 DATA_DIR=/tmp/lq python3 server.py

    # 首次需要生成令牌文件
    python3 server.py --init-tokens

## 环境变量

    PORT            监听端口，默认 8790
    HOST            监听地址，默认 0.0.0.0
    DATA_DIR        数据目录，默认 ./data
    TOKEN_FILE      令牌文件，默认 $DATA_DIR/auth.json
    DEFAULT_TTL     任务默认有效期（秒），默认 600
    MAX_ATTEMPTS    单个任务最大下发次数，默认 4

## 只用标准库

没有 Flask / FastAPI 依赖，python3 直接跑。方便对照阅读。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8790"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
TOKEN_FILE = Path(os.environ.get("TOKEN_FILE", str(DATA_DIR / "auth.json")))
TASKS_FILE = DATA_DIR / "tasks.json"
DEFAULT_TTL = int(os.environ.get("DEFAULT_TTL", "600"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "4"))

LOCK = threading.Lock()


# ---------------------------------------------------------------- 存储

def load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_tasks() -> list[dict]:
    d = load_json(TASKS_FILE, {"tasks": []})
    return d.get("tasks", []) if isinstance(d, dict) else d


def save_tasks(tasks: list[dict]) -> None:
    save_json(TASKS_FILE, {"tasks": tasks})


# ---------------------------------------------------------------- 鉴权

def sha(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def identify(token: str) -> list[str] | None:
    """返回该令牌的角色列表；未登记返回 None。"""
    if not token:
        return None
    entry = load_json(TOKEN_FILE, {"tokens": []})
    want = sha(token)
    roles: list[str] | None = None
    for t in entry.get("tokens", []):
        # 常数时间比较，且对所有条目都跑一遍，不提前 break
        if hmac.compare_digest(want, sha(t.get("token", ""))):
            roles = t.get("roles", [])
    return roles


def require(header: str | None, role: str) -> bool:
    if not header or not header.startswith("Bearer "):
        return False
    roles = identify(header[7:].strip())
    return bool(roles and role in roles)


# ---------------------------------------------------------------- 业务

def now_ms() -> int:
    return int(time.time() * 1000)


def enqueue(action: str, params: dict, idem: str, ttl: int) -> dict:
    with LOCK:
        tasks = load_tasks()
        # 幂等：同一个 key 已存在就返回原任务
        for t in tasks:
            if t.get("idempotencyKey") == idem:
                return {"task": t, "duplicate": True}
        task = {
            "taskId": "task_" + secrets.token_hex(12),
            "action": action,
            "params": params or {},
            "idempotencyKey": idem,
            "status": "pending",
            "attempts": 0,
            "createdAt": now_ms(),
            "expiresAt": now_ms() + max(ttl, 0) * 1000,
            "receipt": None,
        }
        tasks.append(task)
        save_tasks(tasks)
        return {"task": task}


def take_outbox(limit: int = 10) -> list[dict]:
    """取待执行任务并标记为已下发（attempts+1）。过期的直接判失败。"""
    with LOCK:
        tasks = load_tasks()
        now = now_ms()
        picked: list[dict] = []
        changed = False
        for t in tasks:
            if t.get("status") != "pending" or t.get("receipt"):
                continue
            if t.get("expiresAt", 0) <= now:
                t["status"] = "failed"
                t["receipt"] = {"status": "failed", "error": "expired"}
                changed = True
                continue
            t["attempts"] = t.get("attempts", 0) + 1
            t["status"] = "dispatched"
            t["dispatchedAt"] = now
            picked.append(t)
            changed = True
            if len(picked) >= limit:
                break
        if changed:
            save_tasks(tasks)
        return picked


def apply_receipt(task_id: str, status: str, result=None, error=None) -> bool:
    with LOCK:
        tasks = load_tasks()
        for t in tasks:
            if t.get("taskId") != task_id:
                continue
            t["receipt"] = {"status": status, "result": result, "error": error,
                            "at": now_ms()}
            t["status"] = status
            save_tasks(tasks)
            return True
    return False


def reap() -> int:
    """把超过最大下发次数还没回执的任务判为失败。"""
    with LOCK:
        tasks = load_tasks()
        n = 0
        for t in tasks:
            if t.get("receipt"):
                continue
            if t.get("attempts", 0) >= MAX_ATTEMPTS:
                t["status"] = "failed"
                t["receipt"] = {"status": "failed", "error": "max_attempts_reached",
                                "at": now_ms()}
                n += 1
        if n:
            save_tasks(tasks)
        return n


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "ShortcutQueue/1.0"

    def log_message(self, fmt, *args):  # 安静一点
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ---- 工具
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def _need(self, role: str) -> bool:
        if require(self.headers.get("Authorization"), role):
            return True
        self._send(401, {"error": "unauthorized"})
        return False

    # ---- 路由
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._send(200, {"ok": True, "service": "shortcut-queue",
                                    "time": now_ms()})
        if u.path == "/outbox":
            if not self._need("phone"):
                return
            reap()
            q = parse_qs(u.query)
            limit = int(q.get("limit", ["10"])[0])
            return self._send(200, {"tasks": take_outbox(limit)})
        if u.path == "/tasks":
            if not self._need("admin"):
                return
            q = parse_qs(u.query)
            tid = q.get("taskId", [None])[0]
            tasks = load_tasks()
            if tid:
                hit = [t for t in tasks if t.get("taskId") == tid]
                return self._send(200, {"tasks": hit})
            return self._send(200, {
                "total": len(tasks),
                "pending": sum(1 for t in tasks
                               if t.get("status") == "pending" and not t.get("receipt")),
            })
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()

        if u.path == "/tasks":
            if not self._need("admin"):
                return
            action = (body.get("action") or "").strip()
            idem = (body.get("idempotencyKey") or "").strip()
            if not action:
                return self._send(422, {"error": "action.required"})
            if not idem:
                return self._send(422, {"error": "idempotency_key.required"})
            raw_ttl = body.get("ttlSeconds")
            ttl = DEFAULT_TTL if raw_ttl is None else int(raw_ttl)
            r = enqueue(action, body.get("params") or {}, idem, ttl)
            return self._send(201 if not r.get("duplicate") else 200, r)

        if u.path == "/receipt":
            if not self._need("phone"):
                return
            tid = (body.get("taskId") or "").strip()
            status = (body.get("status") or "succeeded").strip()
            if not tid:
                return self._send(422, {"error": "taskId.required"})
            ok = apply_receipt(tid, status, body.get("result"), body.get("error"))
            return self._send(200 if ok else 404, {"ok": ok})

        return self._send(404, {"error": "not_found"})


class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def init_tokens() -> None:
    if TOKEN_FILE.exists():
        print(f"令牌文件已存在，未覆盖：{TOKEN_FILE}")
        return
    save_json(TOKEN_FILE, {"tokens": [
        {"token": secrets.token_urlsafe(32), "roles": ["admin"]},
        {"token": secrets.token_urlsafe(32), "roles": ["phone"]},
    ]})
    print(f"已生成令牌文件：{TOKEN_FILE}")
    print("  admin 令牌用于入队，phone 令牌装进手机的快捷指令")


def main(argv: list[str]) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if "--init-tokens" in argv:
        init_tokens()
        return 0
    if not TOKEN_FILE.exists():
        print(f"缺少令牌文件 {TOKEN_FILE}，先运行：python3 server.py --init-tokens")
        return 1
    srv = Server((HOST, PORT), Handler)
    print(f"任务队列服务已启动 http://{HOST}:{PORT}")
    print(f"  数据目录 {DATA_DIR.resolve()}")
    print(f"  任务文件 {TASKS_FILE}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
