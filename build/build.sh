#!/usr/bin/env bash
# build.sh — 快捷指令一条命令出成品：校验注册表 → 生成 → 签名 → 交付 → 结构自检
#
# 更新日期：2026-10-15　状态：生效
# 上游规范：docs/快捷指令制作规范.md；接口约定见 AGENTS.md
#   （set -u / source wk.sh / 支持 --dry-run / 日志走 wk_log / 不再手写绝对路径）
#
# 用法：
#   build/build.sh                      # 出 v 递增版本 + 更新交付副本
#   build/build.sh --version v14        # 指定版本号
#   build/build.sh --dry-run            # 只打印将要执行的步骤，不生成/不签名/不复制
#   build/build.sh --publish            # 额外复制到静态站目录（可选，直链分发用）
#
# 环境变量（禁硬编码环境事实，全部可覆盖）：
#   SHORTCUT_SIGN / SHORTCUT_SIGN_LIB / SHORTCUT_DELIVER / TASKQUEUE_BASE
#   SHORTCUT_SERVE 仅在显式加 --publish 时使用（可选，静态站直链分发）
set -euo pipefail

SG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$SG/.venv/bin/python"
SIGN="${SHORTCUT_SIGN:-/usr/local/bin/shortcut-sign}"
LD="${SHORTCUT_SIGN_LIB:-$SG/lib}"
DELIVER_DIR="${SHORTCUT_DELIVER:-$HOME/shortcut-deliver}"
SERVE_ROOT="${SHORTCUT_SERVE:-}"   # 可选，仅 --publish 时使用
NAME="${NAME:-ShortcutPull}"

DRY=0
BUMP=0
PUBLISH=0
VERSION=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --bump) BUMP=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --publish) PUBLISH=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

# 统一日志出口（wk.sh 提供 wk_log/wk_bin/wk_notify；缺失时降级为 stderr，不静默）
WK_NAME="${WK_NAME:-build-shortcut}"
# 状态/日志目录：约定 /var/log + /var/lib/<名>/。非特权用户跑不动则回退到工作区，仍不吞错。
if [ ! -w /var/log ]; then
  WK_LOG="${WK_LOG:-$SG/out/build-shortcut.log}"
fi
if [ -r /usr/local/lib/wk.sh ]; then
  # shellcheck disable=SC1091
  . /usr/local/lib/wk.sh
else
  wk_log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >&2; }
  wk_notify() { printf 'NOTIFY: %s\n' "$*" >&2; }
fi

log() { printf '\033[1m== %s\033[0m\n' "$*"; wk_log "== $*"; }
die() { printf '\033[1m✗ %s\033[0m\n' "$*" >&2; wk_log "FAIL: $*"; [ "$DRY" = 1 ] || wk_notify "build-shortcut 失败: $*" 2>/dev/null || true; exit 1; }
run() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }

# ---------- 0. 环境 ----------
[ "$DRY" = 1 ] || [ -x "$PY" ] || die "找不到 venv python: $PY"
[ "$DRY" = 1 ] || [ -x "$SIGN" ] || die "找不到签名器: $SIGN（可用 SHORTCUT_SIGN 覆盖）"
[ "$DRY" = 1 ] || [ -f "$SG/certs/key.bin" ] || die "缺私钥 certs/key.bin（本机专属，不应出机器）"
[ "$DRY" = 1 ] || [ -f "$SG/certs/auth.plist" ] || die "缺 auth data certs/auth.plist"

# 版本号：由 build/version.json 维护。用法见 docs/快捷指令制作规范.md。
# 规则：小改（改参数、改文案）沿用当前版本；大改（加/删动作、改派发结构）才 +1。
#   build/build.sh                       -> 读 version.json 当前版本
#   build/build.sh --bump                -> 先 +1 再构建
#   build/build.sh --version v14         -> 强制指定
if [ -z "$VERSION" ]; then
  VFILE="$SG/build/version.json"
  cur=1
  [ -r "$VFILE" ] && cur=$($PY -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$VFILE" 2>/dev/null || echo 1)
  if [ "$BUMP" = 1 ]; then cur=$(( cur + 1 )); fi
  VERSION="v$cur"
  [ "$DRY" = 1 ] || $PY -c "import json,sys;p=sys.argv[1];d={'version':int(sys.argv[2])};json.dump(d,open(p,'w'))" "$VFILE" "${VERSION#v}" 2>/dev/null || true
fi
case "$VERSION" in v[0-9]*) ;; *) die "版本号要形如 v14，收到 $VERSION" ;; esac

# ---------- 1. 注册表 → 服务端（只查漂移，不自动改） ----------
log "1/6 校验注册表与 taskqueue ACTIONS 是否同步"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] $PY $SG/build/sync_server.py --check"
elif ! "$PY" "$SG/build/sync_server.py" --check; then
  die "服务端 ACTIONS 与 actions.json 不同步；先运行： $PY $SG/build/sync_server.py"
fi

# ---------- 2. 生成 ----------
log "2/6 从 actions.json 生成快捷指令"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] $PY $SG/build/build_pull.py --out $SG/out/$NAME.shortcut --json"
else
  "$PY" "$SG/build/build_pull.py" --out "$SG/out/$NAME.shortcut" --json | tee "$SG/out/$NAME.build.json"
fi
echo

# ---------- 3. 签名 ----------
log "3/6 自签（shortcut-sign sign）"
run env LD_LIBRARY_PATH="$LD" "$SIGN" sign \
  -i "$SG/out/$NAME.shortcut" \
  -o "$SG/certs/$NAME-$VERSION-signed.shortcut" \
  -k "$SG/certs/key.bin" \
  -a "$SG/certs/auth.plist"

# ---------- 4. 结构自检（签名件反解回未签名件再比对） ----------
log "4/6 结构自检"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] extract + 动作数/动作序列比对"
else
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT
  if ! LD_LIBRARY_PATH="$LD" "$SIGN" extract -i "$SG/certs/$NAME-$VERSION-signed.shortcut" -o "$TMP/extracted.shortcut"; then
    die "签名件无法反解（signature/extract 失败）"
  fi
  "$PY" - "$SG/out/$NAME.shortcut" "$TMP/extracted.shortcut" <<'PY'
import plistlib, sys
a = plistlib.load(open(sys.argv[1], "rb"))
b = plistlib.load(open(sys.argv[2], "rb"))
na, nb = len(a["WFWorkflowActions"]), len(b["WFWorkflowActions"])
ids_a = [x["WFWorkflowActionIdentifier"] for x in a["WFWorkflowActions"]]
ids_b = [x["WFWorkflowActionIdentifier"] for x in b["WFWorkflowActions"]]
print(f"  签名件可反解：动作数 {nb}（生成件 {na}）")
assert na == nb, f"动作数不一致 {na} != {nb}"
assert ids_a == ids_b, "动作序列不一致"
assert a["WFWorkflowName"] == b["WFWorkflowName"] == "ShortcutPull", "显示名不对"
print(f"  显示名: {b['WFWorkflowName']} ｜ 动作序列一致 ✅")
PY
  LD_LIBRARY_PATH="$LD" "$SIGN" info -i "$SG/certs/$NAME-$VERSION-signed.shortcut" 2>&1 | sed -n '1,5p' | sed 's/^/  /'
fi

# ---------- 4b. 结构门禁（vendor/shortcut-cli） ----------
log "4b 结构门禁（canonical / 控制流配对）"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] $PY $SG/build/verify_struct.py $SG/out/$NAME.shortcut"
else
  "$PY" "$SG/build/verify_struct.py" "$SG/out/$NAME.shortcut" || die "结构门禁不通过（见上）"
fi

# ---------- 5. 交付 ----------
log "5/6 交付副本"
run cp -f "$SG/certs/$NAME-$VERSION-signed.shortcut" "$SG/certs/$NAME-signed.shortcut"
run cp -f "$SG/out/$NAME.shortcut" "$SG/out/$NAME.$VERSION.shortcut"
# 默认只出文件；把文件送到手机用任何你顺手的方式（即时通讯 / AirDrop / 网盘）
# 加 --publish 才会复制到静态站目录，用于团队批量分发
DELIVER_TARGETS="交付目录:$DELIVER_DIR"
if [ "$PUBLISH" = 1 ]; then
  if [ -z "$SERVE_ROOT" ]; then
    echo "  ⚠ 已加 --publish 但未设 SHORTCUT_SERVE，跳过静态站复制" >&2
  else
    DELIVER_TARGETS="$DELIVER_TARGETS|静态站:$SERVE_ROOT"
  fi
fi

IFS='|'
for pair in $DELIVER_TARGETS; do
  label="${pair%%:*}"; dir="${pair#*:}"
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] install -m 644 ... $dir/$NAME.shortcut"
  elif [ -d "$dir" ] && [ -w "$dir" ]; then
    install -m 644 "$SG/certs/$NAME-signed.shortcut" "$dir/$NAME.shortcut"
    echo "  $label 副本: $dir/$NAME.shortcut"
  else
    echo "  ⚠ $label 目标不可写，已跳过: $dir（可用环境变量指定）" >&2
    wk_log "SKIP: $label 目标不可写 $dir"
  fi
done
unset IFS
if [ "$PUBLISH" = 1 ]; then
  echo "  静态站路径: $SERVE_ROOT/$NAME.shortcut"
fi

# ---------- 6. 汇总 ----------
log "6/6 完成 $VERSION"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] 未产生任何文件"
else
  ls -la "$SG/certs/$NAME-$VERSION-signed.shortcut" | sed 's/^/  /'
  wk_log "OK: $NAME $VERSION 已生成并交付"
fi
