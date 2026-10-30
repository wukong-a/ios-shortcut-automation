#!/usr/bin/env python3
"""wake.py — 邮件唤醒：让手机主动去拉任务。

## 为什么需要这一步

iOS 不允许服务器主动推送指令到手机。快捷指令只能在「被触发」时运行，
而唯一能做到**无人工参与触发**的通道是「收到特定邮件」自动化：

    服务端入队任务  →  发一封唤醒邮件  →  手机邮件自动化命中
    →  运行快捷指令  →  拉取任务队列  →  执行  →  回传结果

邮件正文本身不是指令，只是一个「信号弹」。真正的任务内容在队列里，
手机拉取时才决定执行什么。这样做的好处：邮件被转发/截图都不泄露任务内容。

## 用法

    python3 wake.py                          # 纯唤醒（正文固定）
    python3 wake.py "自定义正文"
    python3 wake.py --dry-run                # 只打印配置，不发信

## 配置（环境变量，均可覆盖）

    WAKE_SMTP_HOST     SMTP 服务器（必填，需自备发信服务）
    WAKE_SMTP_PORT     端口，默认 465（SSL）；587 为 STARTTLS
    WAKE_SUBJECT       邮件主题，默认 "Shortcut Trigger"
    WAKE_TO            收件地址（需与手机自动化的匹配规则一致）
    WAKE_FROM          发件账号
    WAKE_SMTP_USER     SMTP 登录名
    WAKE_SMTP_PASS     SMTP 授权码（建议放 .env 或密钥管理，勿硬编码）
    WAKE_ENV_FILE      可选，从该文件预加载上面这些变量（默认 ~/.shortcut-env）

未配置 SMTP 时不发信，改用 --dry-run 或用别的唤醒通道（见 README「前提」）。

## 手机端配置（一次性）

1. 快捷指令 App → 自动化 → 新建
2. 触发条件选「电子邮件」，发件人填 WAKE_FROM，主题包含 WAKE_SUBJECT
3. 关闭「运行前询问」
4. 动作选「运行快捷指令」→ 你的任务拉取快捷指令
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys
from email.mime.text import MIMEText

DEFAULT_SUBJECT = "Shortcut Trigger"
DEFAULT_BODY = "wake"


def load_dotenv(path: str | None = None) -> None:
    """轻度读取 .env：只补齐尚未存在的环境变量。"""
    path = path or os.environ.get("WAKE_ENV_FILE") or os.path.expanduser("~/.shortcut-env")
    if not os.path.isfile(path):
        return
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


def config() -> dict:
    load_dotenv()
    return {
        "host": os.environ.get("WAKE_SMTP_HOST", ""),
        "port": int(os.environ.get("WAKE_SMTP_PORT", "465")),
        "subject": os.environ.get("WAKE_SUBJECT", DEFAULT_SUBJECT),
        "to": os.environ.get("WAKE_TO", ""),
        "from": os.environ.get("WAKE_FROM", ""),
        "user": os.environ.get("WAKE_SMTP_USER", ""),
        "password": os.environ.get("WAKE_SMTP_PASS", ""),
    }


def send(body: str = DEFAULT_BODY, cfg: dict | None = None) -> bool:
    cfg = cfg or config()
    missing = [k for k in ("to", "from", "user", "password") if not cfg[k]]
    if missing:
        raise SystemExit(f"缺少配置：{', '.join(missing)}（见文件头说明）")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = cfg["subject"]
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]

    ctx = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=20) as s:
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["from"], [cfg["to"]], msg.as_string())
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
            s.starttls(context=ctx)
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["from"], [cfg["to"]], msg.as_string())
    return True


def main(argv: list[str]) -> int:
    if "--dry-run" in argv:
        cfg = config()
        for k, v in cfg.items():
            shown = "***" if k == "password" and v else (v or "(未设置)")
            print(f"{k:10s} = {shown}")
        return 0
    body = argv[0] if argv and not argv[0].startswith("--") else DEFAULT_BODY
    send(body)
    print("✓ 唤醒邮件已发送")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
