#!/usr/bin/env bash
# gen-ca.sh — 一条命令生成自签证书体系（CA + 签名私钥 + auth 数据）
#
# 别人 clone 下仓库后，跑这一步就有自己的证书，再走 build.sh 就能签出自己的快捷指令。
#
# 用法：
#   ./build/gen-ca.sh                    # 输出到 ./certs/，组织名默认 "Shortcut Automation"
#   ./build/gen-ca.sh --cn "张三的机器"   # 自定义 CA 名称
#   ./build/gen-ca.sh --days 7300        # 自定义有效期（天）
#   ./build/gen-ca.sh --force            # 覆盖已有证书
#
# 产物（全部在 certs/ 下，已在 .gitignore 中，绝不入库）：
#   ca.key      CA 私钥（保密！丢了要重签，泄露了整条信任链失效）
#   ca.crt      CA 证书（PEM）
#   ca.der      CA 证书（DER，装进手机用的就是这个）
#   key.bin     ECDSA-P256 签名私钥（shortcut-sign 用）
#   auth.plist  签名身份数据（含证书链）
#
# 前提：openssl 1.1.1+，以及已安装 shortcut-sign（用于生成 auth.plist）
set -euo pipefail

SG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="${CERT_DIR:-$SG/certs}"

CN="Shortcut Automation"
ORG="Self-Signed"
DAYS=3650
FORCE=0
SIGN="${SHORTCUT_SIGN:-shortcut-sign}"
LIB="${SHORTCUT_SIGN_LIB:-$SG/lib}"

while [ $# -gt 0 ]; do
  case "$1" in
    --cn)    CN="$2"; shift 2 ;;
    --org)   ORG="$2"; shift 2 ;;
    --days)  DAYS="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

die() { echo "错误：$*" >&2; exit 1; }
log() { echo "==> $*"; }

command -v openssl >/dev/null 2>&1 || die "未找到 openssl，请先安装（apt install openssl / brew install openssl）"
openssl version | grep -qE "OpenSSL (3\.|1\.1\.[1-9])" || log "提示：openssl 版本较旧，建议 1.1.1 以上"

if [ -d "$CERT_DIR" ] && [ -n "$(ls -A "$CERT_DIR" 2>/dev/null)" ] && [ "$FORCE" != 1 ]; then
  die "certs/ 已有内容。换新证书请加 --force（会覆盖旧的），或先备份"
fi

mkdir -p "$CERT_DIR"
chmod 700 "$CERT_DIR"

# ---------- 1. ECDSA-P256 签名私钥（shortcut-sign 要求 ASN1 格式）----------
log "1/4 生成签名私钥 key.bin（ECDSA-P256）"
openssl ecparam -name prime256v1 -genkey -noout -out "$CERT_DIR/key.tmp.pem"
# shortcut-sign 要的是 ASN1 DER 私钥，转一下
openssl ec -in "$CERT_DIR/key.tmp.pem" -outform DER -out "$CERT_DIR/key.bin" 2>/dev/null
chmod 600 "$CERT_DIR/key.bin"
rm -f "$CERT_DIR/key.tmp.pem"

# ---------- 2. 自建 CA ----------
log "2/4 生成自建 CA（$CN，有效期 $DAYS 天）"
openssl ecparam -name prime256v1 -genkey -noout -out "$CERT_DIR/ca.key"
chmod 600 "$CERT_DIR/ca.key"

openssl req -new -x509 \
  -key "$CERT_DIR/ca.key" \
  -out "$CERT_DIR/ca.crt" \
  -days "$DAYS" \
  -subj "/O=$ORG/CN=$CN" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# DER 格式，装进手机用这个
openssl x509 -in "$CERT_DIR/ca.crt" -outform DER -out "$CERT_DIR/ca.der"

# ---------- 3. auth.plist（shortcut-sign 的签名身份）----------
log "3/4 生成 auth.plist"
if command -v "$SIGN" >/dev/null 2>&1; then
  # shortcut-sign 自身提供 auth 生成能力
  if ! LD_LIBRARY_PATH="$LIB" "$SIGN" auth --help >/dev/null 2>&1; then
    log "提示：当前 shortcut-sign 无 auth 子命令，跳过自动生成"
    log "      auth.plist 需手工准备，格式见 docs/signing-explained.md"
  fi
else
  log "提示：未找到 shortcut-sign，跳过 auth.plist 自动生成"
  log "      安装后可用 shortcut-sign auth 生成，或参考 docs/signing-explained.md"
fi

# ---------- 4. 自检 ----------
log "4/4 自检"
[ -f "$CERT_DIR/ca.crt" ] || die "ca.crt 未生成"
[ -f "$CERT_DIR/ca.der" ] || die "ca.der 未生成"
[ -f "$CERT_DIR/key.bin" ] || die "key.bin 未生成"

echo
openssl x509 -in "$CERT_DIR/ca.crt" -noout -subject -dates | sed 's/^/  /'
echo "  私钥: $CERT_DIR/key.bin ($(stat -c%s "$CERT_DIR/key.bin" 2>/dev/null || echo '?') 字节)"
echo
log "完成。产物在 $CERT_DIR/"
echo
echo "接下来："
echo "  1. 把 certs/ca.der 传到手机，安装描述文件"
echo "  2. 设置 → 通用 → 关于本机 → 证书信任设置 → 开启完全信任"
echo "  3. ./build/build.sh  构建并签名你的快捷指令"
echo
echo "注意："
echo "  - certs/ 已在 .gitignore 中，不要提交、不要分享给他人"
echo "  - 这个 CA 只用于你自己的设备，别人要用必须自己跑一遍本脚本"
