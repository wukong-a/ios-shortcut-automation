"""config.py — 快捷指令流水线的可覆盖配置。

依「禁硬编码环境事实」：这里给出的是**默认值**，全部可用环境变量覆盖，
不在代码里散落绝对路径。改机器/换服务只需设环境变量，不动脚本。

    TASKQUEUE_BASE      任务队列 HTTP 地址
    TASKQUEUE_SERVER    taskqueue 服务端文件路径
    TASKQUEUE_SERVICE   systemd 服务名
    TASKQUEUE_TOKEN     手机令牌文件路径（含令牌的单一真相源）
    SHORTCUT_SIGN       shortcut-sign 可执行文件
    SHORTCUT_SIGN_LIB   libplist-2.0.so.4 所在目录
    SHORTCUT_KEY        签名私钥
    SHORTCUT_AUTH       签名 auth 数据
    SHORTCUT_DELIVER    交付输出目录
    SHORTCUT_SERVE      （可选）静态文件根目录，仅 --publish 分发时使用
    SHORTCUT_DOC        台账文档路径（供 verify_all 核对文档漂移）
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SG = HERE.parent                      # 仓库根下 tools/shortcutgen
ROOT = SG.parent


def env_path(name: str, default: str) -> Path:
    p = os.environ.get(name) or default
    return Path(os.path.expanduser(p))


BASE = os.environ.get("TASKQUEUE_BASE") or "https://task.example.com"
SERVER_MJS = env_path("TASKQUEUE_SERVER", "/srv/taskqueue/server.mjs")
SERVICE_NAME = os.environ.get("TASKQUEUE_SERVICE") or "taskqueue"
TOKEN_PATH = env_path("TASKQUEUE_TOKEN", "/srv/taskqueue/phone-token.txt")

SIGN_BIN = os.environ.get("SHORTCUT_SIGN") or "/usr/local/bin/shortcut-sign"
SIGN_LIB = env_path("SHORTCUT_SIGN_LIB", str(SG / "lib"))
SIGN_KEY = env_path("SHORTCUT_KEY", str(SG / "certs" / "key.bin"))
SIGN_AUTH = env_path("SHORTCUT_AUTH", str(SG / "certs" / "auth.plist"))

DELIVER_DIR = env_path("SHORTCUT_DELIVER", "~/shortcut-deliver")
# 静态站分发为可选功能；不设则为空，build.sh --publish 时才用到
SERVE_ROOT = env_path("SHORTCUT_SERVE", "")
DOC_LEDGER = env_path("SHORTCUT_DOC", str(ROOT / "docs" / "快捷指令清单.md"))

REGISTRY = SG / "build" / "actions.json"
CATEGORIES = SG / "examples" / "shortcut-categories.example.json"
SHORTCUTS = SG / "shortcuts.json"
OUT_DIR = SG / "out"
CERTS = SG / "certs"
