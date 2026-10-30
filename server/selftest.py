#!/usr/bin/env python3
"""回归自测：任务队列服务端。

在隔离环境（临时目录 + 独立端口）跑，不碰任何真实数据。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server", "server.py")
PORT = 18800
BASE = f"http://127.0.0.1:{PORT}"


def req(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sq-test-")
    env = dict(os.environ, DATA_DIR=tmp, PORT=str(PORT), HOST="127.0.0.1")
    try:
        subprocess.run([sys.executable, SERVER, "--init-tokens"], env=env,
                       check=True, capture_output=True)
        toks = json.load(open(os.path.join(tmp, "auth.json")))["tokens"]
        admin = [t["token"] for t in toks if "admin" in t["roles"]][0]
        phone = [t["token"] for t in toks if "phone" in t["roles"]][0]

        proc = subprocess.Popen([sys.executable, SERVER], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        ok = 0
        fail = 0

        def check(name, cond, extra=""):
            nonlocal ok, fail
            if cond:
                ok += 1
                print(f"  ✓ {name} {extra}")
            else:
                fail += 1
                print(f"  ✗ {name} {extra}")

        s, b = req("GET", "/health")
        check("health", s == 200 and b.get("ok") is True, f"({s})")

        s, _ = req("POST", "/tasks", body={"action": "clipboard.get", "idempotencyKey": "x"})
        check("无令牌入队应 401", s == 401, f"({s})")

        s, b = req("POST", "/tasks", admin, {"action": "clipboard.get"})
        check("缺幂等键应 422", s == 422, f"({s} {b.get('error')})")

        s, b = req("POST", "/tasks", admin,
                   {"action": "clipboard.get", "idempotencyKey": "k1", "ttlSeconds": 600})
        tid = (b.get("task") or {}).get("taskId")
        check("正常入队", s == 201 and tid, f"({s} {tid})")

        s, b = req("POST", "/tasks", admin,
                   {"action": "clipboard.get", "idempotencyKey": "k1"})
        check("重复幂等键返回同任务", s == 200 and b.get("duplicate") is True,
              f"same={((b.get('task') or {}).get('taskId')) == tid}")

        s, b = req("GET", "/outbox", phone)
        check("手机拉取", s == 200 and len(b.get("tasks", [])) == 1,
              f"attempts={b['tasks'][0]['attempts'] if b.get('tasks') else '-'}")

        s, b = req("GET", "/outbox", phone)
        check("复核拉取不重复", s == 200 and len(b.get("tasks", [])) == 0)

        s, _ = req("GET", "/outbox", admin)
        check("admin 不能拉取（角色隔离）", s == 401, f"({s})")

        s, b = req("POST", "/receipt", phone,
                   {"taskId": tid, "status": "succeeded", "result": "ok"})
        check("回执", s == 200 and b.get("ok") is True)

        s, b = req("GET", "/tasks", admin)
        check("统计 pending=0", s == 200 and b.get("pending") == 0, str(b))

        # TTL 过期
        s, b = req("POST", "/tasks", admin,
                   {"action": "notify", "idempotencyKey": "k2", "ttlSeconds": 0})
        s, b = req("GET", "/outbox", phone)
        # 过期任务会被判 failed 并写入 receipt，因此既不下发也要落失败状态
        tasks_now = json.load(open(os.path.join(tmp, "tasks.json")))["tasks"]
        k2 = [x for x in tasks_now if x.get("idempotencyKey") == "k2"]
        check("过期任务不下发", s == 200
              and all(x.get("idempotencyKey") != "k2" for x in b.get("tasks", []))
              and k2 and k2[0].get("status") == "failed",
              f"status={k2[0]['status'] if k2 else '-'}")
        s, b = req("GET", "/tasks", admin)
        check("统计不含过期任务", s == 200 and b.get("pending") == 0, str(b))

        # 幂等：并发重复
        ids = set()
        for i in range(3):
            s, b = req("POST", "/tasks", admin,
                       {"action": "notify", "idempotencyKey": "k3"})
            ids.add((b.get("task") or {}).get("taskId"))
        check("多次同幂等键只产生一个任务", len(ids) == 1)

        proc.terminate()
        proc.wait(timeout=5)
        print(f"\n结果：{ok} 通过 / {fail} 失败")
        return 0 if fail == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
