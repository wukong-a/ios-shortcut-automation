# 服务端参考实现

一个**可跑的最小实现**，用标准库写，没有 Flask / FastAPI 依赖。

只做三件事：接收任务 → 交给手机 → 收回结果。

## 跑起来

```bash
cd server
python3 server.py --init-tokens     # 生成 admin / phone 令牌
python3 server.py                   # 默认 0.0.0.0:8790
```

令牌文件长这样：

```json
{
  "tokens": [
    { "token": "…", "roles": ["admin"] },
    { "token": "…", "roles": ["phone"] }
  ]
}
```

`admin` 令牌用于入队，`phone` 令牌装进手机的快捷指令里。

## 四个接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/health` | 无 | 存活检查 |
| POST | `/tasks` | admin | 入队任务 |
| GET | `/outbox` | phone | 手机拉取待执行任务 |
| POST | `/receipt` | phone | 回传结果 |
| GET | `/tasks` | admin | 统计 / 按 taskId 查询 |

### 入队

```bash
curl -X POST http://127.0.0.1:8790/tasks \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{
        "action": "clipboard.get",
        "params": {},
        "idempotencyKey": "clip-1730000000000",
        "ttlSeconds": 600
      }'
```

`idempotencyKey` 必填 —— 手机可能因重试多次拉取，没有它会重复执行。
同一个 key 重复提交会返回原任务并带 `"duplicate": true`。

### 手机拉取

```bash
curl "http://127.0.0.1:8790/outbox?limit=10" \
  -H "Authorization: Bearer $PHONE"
```

拉到的任务会立即标记 `dispatched` 并 `attempts+1`，不会重复下发。

### 回传

```bash
curl -X POST http://127.0.0.1:8790/receipt \
  -H "Authorization: Bearer $PHONE" \
  -H "Content-Type: application/json" \
  -d '{"taskId": "task_xxx", "status": "succeeded", "result": "ok"}'
```

## 任务生命周期

```
pending ──拉取──> dispatched ──回执──> succeeded / failed
   │
   └──超时/超次数──> failed
```

- `ttlSeconds` 到期未执行的，拉取时直接判 `failed / expired`
- 下发次数达 `MAX_ATTEMPTS`（默认 4）仍无回执，判 `failed / max_attempts_reached`
- 每次拉取都会先跑一遍 `reap()`，自动清理陈旧任务

## 安全设计

- 令牌比对用 **sha256 + 常数时间比较**（`hmac.compare_digest`），且不提前 break，避免时序侧信道
- 令牌权限分离：`admin` 只能入队查状态，`phone` 只能拉取回传
- 任务过期自动作废，防止陈旧指令被延迟执行

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8790` | 监听端口 |
| `DATA_DIR` | `./data` | 数据目录 |
| `TOKEN_FILE` | `$DATA_DIR/auth.json` | 令牌文件 |
| `DEFAULT_TTL` | `600` | 任务默认有效期（秒） |
| `MAX_ATTEMPTS` | `4` | 最大下发次数 |

## 自测结果

已跑通 10 项：

```
1) /health ................................ 200
2) 无令牌入队 .............................. 401
3) 缺幂等键 ................................ 422
4) 正常入队 ................................ 201
5) 重复幂等键 .............................. duplicate=true, 同一 taskId
6) 手机拉取 ................................ 1 条, attempts=1
7) 复核拉取 ................................ 0 条（不重复下发）
8) 回执 .................................... ok
9) 最终状态 ................................ succeeded
10) 统计 ................................... total=1, pending=0
```

## 生产部署注意

这是**参考实现**，跑通链路够用，但不覆盖：

- **持久化**：用 JSON 文件，并发高时会成瓶颈。生产换 SQLite / Redis
- **HTTPS**：只监听 HTTP，公网需前置反向代理（Caddy / Nginx / Lucky）
- **限流**：没有请求频率限制，公网暴露需在网关层做
- **任务清理**：`tasks.json` 会一直增长，需定期归档

## 与真实环境的隔离

这份代码完全独立：不读写任何现有服务的数据，不监听默认端口以外的东西，
令牌文件自己生成。

```bash
# 用临时目录和独立端口跑，不碰真实环境
DATA_DIR=/tmp/test-lq PORT=18790 python3 server.py --init-tokens
DATA_DIR=/tmp/test-lq PORT=18790 python3 server.py
```
