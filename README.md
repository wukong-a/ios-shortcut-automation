# iOS 快捷指令自动化

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%2F%20NAS-lightgrey)](#)
[![Dependencies](https://img.shields.io/badge/Dependencies-Stdlib%20only-2ea44f)](#)

**在 Linux / NAS 上生成、自签、交付 iOS 快捷指令，让手机自己干活。**

没有 Mac？没有 iCloud？没有 Xcode？没关系。
只要有台能跑命令的 Linux 机器（NAS、VPS、树莓派都行），就能产出可以直接导入 iPhone 的快捷指令文件，
并且做到**服务端下发 → 手机自动执行 → 结果回传**，全程不需要人手点一下。

> Generate, self-sign and deploy iOS Shortcuts from Linux/NAS — for unattended phone automation.
> No Mac, no iCloud, no Xcode required.

**这是一个还在长的东西，欢迎任何人来提想法、补动作、挑毛病。** 见 [一起把它做更好](#一起把它做更好)。

---

## 这是什么

一套把「写代码」变成「产出可导入的 `.shortcut` 文件」的流水线：

```
声明式动作注册表  →  代码生成  →  结构门禁  →  自签  →  可导入的 .shortcut
   actions.json      build_pull.py   verify_struct.py  shortcut-sign
```

配合一个轻量任务队列，就能做到：**服务端下发指令 → 手机自动执行 → 回执结果**，全程无需人工点击。

## 为什么做这个

iOS 快捷指令官方签名只能在 macOS + iCloud 环境下完成。这带来两个问题：

1. **无法自动化**：想在服务器/CI 上批量产出快捷指令，做不到
2. **无法版本管理**：快捷指令是二进制包，改一次就得手动重做

本项目给出的解法：

- **自签路线**：用 `shortcut-sign` + 自建 CA，在 Linux 上直接产出可导入的 `.shortcut`
- **声明式注册表**：已跑通的 26 个动作全部写在 `build/actions.json` 里，改配置不改代码，新增动作只需加一行
- **构建期门禁**：canonical 结构检查 + 控制流配对检查，防止导入后静默失效

## 自动化架构（核心思路）

**服务器不能主动给 iPhone 下指令。** 快捷指令只能被触发运行，没有常驻进程。

所以需要找到一个「手机自己会感知、且不需要人点」的触发源。本项目的解法是**邮件唤醒**：

```
服务端入队任务  →  发一封唤醒邮件  →  手机邮件自动化命中
                →  运行快捷指令  →  拉取任务队列  →  执行  →  回传结果
```

关键设计：**唤醒邮件里只放信号，不放指令。**

```
Subject: Shortcut Trigger
Body:    wake
```

任务内容全在队列里，手机拉到才知道干什么。好处：

- 邮件被转发、截图、被别人看到，都不泄露任务内容
- 换任务逻辑不用改邮件模板
- 一封邮件可触发一整批任务

为什么不用别的通道：

| 方案 | 无人触发 | 问题 |
|---|---|---|
| 定时任务 | ✅ | 延迟最高 60 分钟 |
| 推送通知 | ❌ | 需要人点 |
| URL scheme | ❌ | 需要另一台设备 |
| **收到邮件** | ✅ | **零人工，秒级触发** |

手机端一次性配置：快捷指令 → 自动化 → 触发条件选「电子邮件」→ **关闭「运行前询问」**。

实测数据：手机拉取到回执 **600ms**，含邮件触发全链路约 **55 秒**。

### ⚠️ 前提：你需要一个自己的发信服务

本项目**不提供**公共邮件发送服务。`build/wake.py` 只是一个发信客户端，需要你自备：

| 要素 | 说明 |
|---|---|
| SMTP 服务器 | 自建 Postfix / 云厂商邮件推送 / 任意可编程发信的邮箱 |
| 发信账号 | 能发出邮件即可，不需要收件能力 |
| 收件地址 | 手机「邮件」App 里已登录的那个邮箱 |

配置走环境变量，代码里不含任何账号：

```bash
export WAKE_SMTP_HOST=smtp.example.com   # 发信服务器
export WAKE_SMTP_PORT=465                # 465=SSL，587=STARTTLS
export WAKE_FROM=bot@example.com         # 发件账号（手机自动化的匹配条件）
export WAKE_TO=you@example.com           # 收件地址（手机邮件 App 里已登录的）
export WAKE_SMTP_USER=bot@example.com    # SMTP 登录名
export WAKE_SMTP_PASS=******             # 授权码，建议放 .env，勿入库
export WAKE_SUBJECT="Shortcut Trigger"   # 邮件主题，需与手机端规则一致
```

**没有发信服务怎么办**：邮件只是其中一种唤醒通道。这个框架的核心是
「入队 → 唤醒 → 拉取 → 执行 → 回执」这个闭环，**唤醒那一步可以换成任何你能自动触发的方式**：

| 替代唤醒方式 | 做法 | 代价 |
|---|---|---|
| 定时轮询 | 手机自动化每小时跑一次拉取 | 延迟最高 1 小时 |
| 推送 App / 第三方 webhook | 手机端把通知转成快捷指令触发 | 依赖第三方 App |
| 本地网络事件 | 到家连上 Wi-Fi 触发 | 只在特定场景 |
| NFC 贴纸 / 捷径按钮 | 人碰一下才触发 | 需要人工 |
| **任意自定义** | 只要能「无人工地让手机跑起那个快捷指令」就行 | — |

换句话说：**邮件不是必须的，能自动唤醒手机才是必须的。** 你有更好的办法，直接替换 `wake.py` 那一步即可，
其余部分（入队、拉取、执行、回执）完全不用动。

完整架构、时序图、失败模式与对策见 [`docs/automation-architecture.md`](docs/automation-architecture.md)。

服务端那一半给了可跑的参考实现：[`server/server.py`](server/server.py)，纯标准库，`python3 server.py --init-tokens && python3 server.py` 就能用。

## 怎么把文件送到手机

签好名之后只差最后一步：把一个几百 KB 的文件弄到手机上。**没有唯一正确的方式，找个顺手的就行。**

| 方式 | 适合场景 | 代价 |
|---|---|---|
| **即时通讯转文件**（推荐） | 日常自用，一两台设备 | 无 |
| AirDrop | 有 Mac，一次传多个 | 需要 Mac |
| 网盘 / 邮件附件 | 异地、跨网络 | 需登录 |
| 局域网临时服务 | 手边有服务器、内网互通 | 开一次服务 |
| 静态站直链 | 团队批量分发 | 要维护域名、证书、权限、公网暴露 |

**推荐用即时通讯直接发文件**：QQ / 微信 / Telegram 都行，点开就是「导入到快捷指令」，一两步搞定，不用维护任何基础设施。

静态站直链是**可选方案**，只在「一群人都要同一个文件」时才值得。它带来的额外成本是：域名、HTTPS 证书、目录权限、公网暴露面。个人自用完全没必要。

> 交付方式不影响生成与签名质量。选最省事的那条路就好。

## 核心设计

### 1. 动作注册表（`build/actions.json`）

动作的单一真相源。每个动作分两面定义：

```json
{
  "action": "clipboard.get",
  "doc": "读手机剪贴板",
  "server": { "params": {} },
  "phone": { "handler": "clipboard_get", "receipt": { "onSuccess": "succeeded" } }
}
```

- `server`：服务端校验规格（参数类型、范围、白名单）
- `phone`：快捷指令内的实现分支

改动作只改这一份文件，生成器与服务端同步脚本都从这里读。

> **关于「26 个」**
>
> 仓库里这 26 个动作是**本项目实测跑通的集合**，不是 iOS 的能力上限，也不是框架限制。
> iOS 快捷指令本身的动作库有上千个，这套框架对动作数量没有上限——
>
> - **想加动作**：在 `build/actions.json` 补一条，跑一次 `build/build.sh`，
>   手机端分支、服务端校验、结构门禁三处自动对齐，无需手改其它文件
> - **为什么没放全**：每个动作都要经过「服务端能否下发 → 手机能否无人值守执行」的验证，
>   没跑通的不列进来，避免读者以为写进去就能用
> - **没有硬上限**：动作多了构建变慢、导入变慢，但不会失败
>
> 现有 26 个的覆盖面：读取手机状态 5、写入/控制手机 10、内容采集上传 3、
> 系统应用写入 4、调用外部能力 4。

### 怎么新增一个动作

```jsonc
// build/actions.json 里追加
{
  "action": "wifi.toggle",          // 动作名，服务端与手机端的唯一标识
  "doc": "开关 Wi-Fi",
  "server": { "params": {} },       // 参数校验规格
  "phone":  { "steps": [ /* 快捷指令步骤 */ ] }
}
```

然后：

```bash
./build/build.sh          # 生成 .shortcut + 同步服务端 + 门禁检查
```

**不要手改生成结果**（`server.mjs` 的 ACTIONS、`out/*.shortcut`），下次同步会覆盖，校验会报漂移。

### 2. 构建门禁

导入 iOS 后出现「点了没反应」是最难排查的问题。`verify_struct.py` 在构建期就拦住两类静默失败：

- **canonical 结构**：顶层 `UUID` / `GroupingIdentifier` 会被新版导入器丢弃
- **控制流配对**：每个 `If` 必须有对应的 `End If`，不配对会在运行期行为异常

```
✓ canonical OK（214 动作）
✓ 控制流配对 OK（30 开 / 30 关）
```

### 3. 自签交付

```
certs/key.bin  +  certs/auth.plist  →  shortcut-sign  →  xxx-signed.shortcut
```

手机端需安装自建 CA 描述文件并完全信任（非官方路径，苹果可能封堵，自用需评估风险）。

**证书要自己生成**——别人无法共用你的证书（私钥不能共享，CA 信任范围也不该转手）。
一条命令搞定：

```bash
./build/gen-ca.sh --cn "我的快捷指令 CA"
```

产出 `certs/` 下的全套：`ca.key` / `ca.crt` / `ca.der`（装手机用）/ `key.bin` / `auth.plist`。

从生成证书到手机导入的**完整步骤、命令、易错点、风险说明**，见
[`docs/signing-explained.md`](docs/signing-explained.md)。

## 快速开始

### 先跑通服务端（可选，验证链路用）

```bash
cd server
python3 server.py --init-tokens     # 生成 admin / phone 令牌
python3 server.py                   # 0.0.0.0:8790

# 跑一遍自测（隔离环境，13 项）
python3 selftest.py
```

### 再构建快捷指令

```bash
# 1. 配置（全部可用环境变量覆盖，见 build/config.py）
export TASKQUEUE_BASE="https://task.example.com"
export SHORTCUT_SIGN="/usr/local/bin/shortcut-sign"
export SHORTCUT_KEY="/path/to/key.bin"
export SHORTCUT_AUTH="/path/to/auth.plist"

# 2. 一条命令构建
bash build/build.sh

# 3. 只看步骤不执行
bash build/build.sh --dry-run

# 4. 生成能力思维导图
python3 build/gen_mindmap.py
```

产物：

| 路径 | 说明 |
|---|---|
| `out/ShortcutPull.shortcut` | 未签名产物 |
| `certs/ShortcutPull-signed.shortcut` | 已签名，可直接导入 |
| `docs/mindmap.html` | 能力思维导图（浏览器直接打开） |

## 目录结构

```
.
├── build/
│   ├── actions.json               动作注册表（核心资产）
│   ├── version.json               当前版本号
│   ├── build_pull.py              生成器
│   ├── verify_struct.py           结构门禁（canonical / 控制流配对）
│   ├── verify_all.py              台账核对
│   ├── gen_mindmap.py             思维导图生成
│   ├── config.py                  可覆盖配置
│   ├── wake.py                    邮件唤醒
│   ├── sync_server.py             与任务队列服务端对齐动作定义
│   ├── gen-ca.sh                  一条命令生成自签证书（CA + 私钥）
│   └── build.sh                   一条命令流水线
├── server/
│   ├── server.py                  服务端参考实现（标准库，直接可跑）
│   ├── selftest.py                隔离环境回归测试（13 项）
│   └── README.md                  接口文档与自测结果
├── docs/
│   ├── automation-architecture.md 自动化架构（邮件唤醒原理）
│   ├── signing-explained.md       自签详解（从零到能导入 iPhone）
│   ├── mindmap.html               思维导图（可视化）
│   └── mindmap.md                 Mermaid 版本
├── examples/
│   ├── minimal-actions.json       最小动作注册表示例
│   └── shortcut-categories.example.json  能力分类示例
├── vendor/
│   ├── shortcut_cli.py            快捷指令解析工具（随附许可证）
│   └── shortcut-cli.LICENSE
├── LICENSE
└── .gitignore
```

## 无人值守能力边界

并非所有快捷指令都能后台跑。按实测经验分为以下几类（示例见 `examples/shortcut-categories.example.json`）：

| 类别 | 说明 | 示例 |
|---|---|---|
| 可无人值守 | 纯自动，可直接进批处理 | 读剪贴板、查电量 |
| 需要文本/URL 输入 | 不传参就卡在输入框 | 向大模型提问 |
| 需要选择照片/视频 | 弹出相册选择器 | 加水印、九宫格切图 |
| 需要外部 App / 人工确认 | 切走 App 即中断 | 签到类、游戏自动化 |
| 场景组合 | 会阻塞后续派发链 | 离家 / 回家场景 |



**关键教训**：批量执行时，只要混入一个需要交互的快捷指令，整条派发链会挂起，后续全部超时。分类不是建议，是护栏。

## 依赖

- `shortcut-sign`（Linux x86_64）—— 自签工具
- `libplist-2.0.so.4` —— 自编依赖
- Python 3.9+
- `vendor/shortcut_cli.py` —— 可选的快捷指令解析/反解工具，随附许可证

服务端与唤醒脚本**只用标准库**，不需要 pip 安装任何东西。

**额外需要自备**：一个可编程发信的 SMTP 服务（见上文「前提」）。没有也能用，换成别的唤醒方式即可。

## 自测

服务端带一套隔离环境回归测试，每次跑都新建临时目录、独立端口，跑完即删：

```bash
cd server && python3 selftest.py
```

覆盖 13 项：

```
✓ health                     ✓ 无令牌入队 401
✓ 缺幂等键 422               ✓ 正常入队 201
✓ 重复幂等键返回同任务        ✓ 手机拉取 attempts=1
✓ 复核拉取不重复             ✓ 角色隔离（admin 不能拉取）
✓ 回执                       ✓ 统计 pending=0
✓ 过期任务不下发 failed      ✓ 多次同幂等键只产生一个任务
```

## 已知限制

- 自签证书非苹果官方，iOS 升级可能失效，需自建 CA 描述文件
- 无 Mac 环境无法使用官方签名路径
- 批量执行存在隐性并发上限，建议分批并留间隔

## 一起把它做更好

这个项目是从个人需求里长出来的，它现在的样子带着很重的「一个人踩坑」痕迹——
26 个动作是我实际跑通的那些，每一处设计背后都对应一次真实的失败。

所以它最有价值的地方，恰恰不是这些已经写好的代码，而是**还没被想到的部分**。

如果你也在做类似的事，这些方向都值得试一试：

| 方向 | 现在的状态 | 可以怎么改进 |
|---|---|---|
| 唤醒通道 | 只实现了一个发信客户端 | 换成 Webhook、推送、局域网事件、NFC，只要能自动唤醒手机 |
| 动作覆盖 | 26 个已验证动作 | 补没验证过的：家庭控制、传感器读取、文件操作、跨 App 编排 |
| 签名方案 | 依赖 Linux 自签二进制 | 独立的纯 Python 实现，或者更强的证书管理流程 |
| 服务端 | 标准库参考实现 | 换成生产级：持久化、并发、多设备、任务优先级 |
| 失败处理 | 重试 4 次后放弃 | 更聪明的退避策略、失败归类、自动降级 |
| 能力分类 | 手工整理的经验清单 | 自动探测某个动作在当前设备上能否无人值守执行 |

### 欢迎提什么都行

- **思路不对**：如果你觉得这套架构有更好的解法，非常想听
- **哪里是坑**：文档写错、代码跑不通、说明看不懂，都算问题
- **用在了别的场景**：自动化报表、设备巡检、定时提醒、服务器监控告警——
  只要你能想到，这个框架大概率用得上，欢迎告诉我你打算怎么用
- **你多写了一层**：哪怕只是一个更简洁的配置写法

**怎么参与**：提 Issue 说想法、提 PR 改代码、或者只是把你的用法写下来给大家参考，都行。
不用是「大改动」才算贡献，**一句「这里我试过，不行」同样有价值**。

> 一个人踩过的坑，写下来就成了后来者的地图。

## 许可

MIT License，详见 [LICENSE](LICENSE)。

`vendor/` 目录下的第三方组件遵循各自许可证（见 `vendor/shortcut-cli.LICENSE`）。

自签路径非苹果官方，苹果可能随时封堵，**商用前请自行评估合规与稳定性风险**。

如果它帮你省了点时间，回来留句话，那就够了。

## 相关

- 自签工具：`shortcut-sign`（Linux x86_64）
- 思维导图：`docs/mindmap.html`，或在线访问项目 Pages
