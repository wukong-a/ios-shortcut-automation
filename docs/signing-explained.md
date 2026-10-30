# 自签详解：从零到能导入 iPhone

> 这篇讲清楚三件事：**签名到底签什么**、**别人拿到这个仓库怎么自己签**、**这套方案的风险在哪**。

---

## 一、为什么需要自签

iOS 快捷指令是**签名文件**，不是普通文本。

你把 `.shortcut` 文件拖进 iPhone，系统会做两步验证：

1. 文件结构是不是合法的快捷指令格式
2. 签名有效性——这份文件是不是可信方签发、有没有被改过

**官方签名只能在 macOS 上完成**：需要登录 iCloud，走「快捷指令」App 或 Xcode 的签名服务。这条路**在 Linux / NAS 上完全走不通**。

自签的思路是：**自己做一套证书，用这套证书签，然后让手机信任这套证书。** 手机端不认识苹果的签名链，但它会信任你手动装进去的根证书。

---

## 二、签名涉及的五样东西

| 文件 | 是什么 | 谁生成 | 要不要保密 |
|---|---|---|---|
| `ca.key` | CA 私钥，签发证书的根 | 你（`gen-ca.sh`） | 🔴 **绝密** |
| `ca.crt` / `ca.der` | CA 证书（PEM / DER） | 你（`gen-ca.sh`） | 公开，要装进手机 |
| `key.bin` | 签名私钥（ECDSA-P256，ASN1 DER） | 你（`gen-ca.sh`） | 🔴 **绝密** |
| `auth.plist` | 签名身份数据（含证书链） | 你（`shortcut-sign` 生成） | 半公开 |
| `xxx.shortcut` | 未签名的生成结果 | `build_pull.py` | 公开 |

私钥一旦泄露，任何人都能签出「看起来是你发的」快捷指令。所以 `certs/` 目录在 `.gitignore` 里，永远不进仓库。

---

## 三、别人用这个仓库，完整流程

### 步骤 0：准备环境

```bash
# 需要三样东西
openssl --version                      # 1.1.1 以上
shortcut-sign --help                   # 自签工具（Linux x86_64）
ls lib/libplist-2.0.so.4               # shortcut-sign 的依赖库
python3 --version                      # 3.9 以上
```

`shortcut-sign` 是本项目依赖的自签二进制，不在仓库里（体积大且平台相关），需要单独获取并放到 `/usr/local/bin/`。

### 步骤 1：生成自己的证书

```bash
git clone https://github.com/wukong-a/ios-shortcut-automation.git
cd ios-shortcut-automation

./build/gen-ca.sh --cn "我的快捷指令 CA" --org "MyName"
```

一条命令产出全套：

```
certs/
├── ca.key      CA 私钥（600 权限）
├── ca.crt      CA 证书 PEM
├── ca.der      CA 证书 DER ← 装进手机用这个
├── key.bin     签名私钥（ECDSA-P256）
└── auth.plist  签名身份数据
```

脚本最后会打印证书信息和后续指引。

**这一步的关键点**：这是**你自己**的证书。别人的证书你签不了你的名字，你的也不该给别人用（理由见第五节）。

### 步骤 2：把 CA 装进手机

三种方式，任选：

| 方式 | 操作 |
|---|---|
| 网页下载 | 把 `ca.der` 放到任意可访问的网址，用 **Safari** 打开 |
| 邮件 | 附件发给自己，手机邮件 App 里点开 |
| AirDrop | Mac 传给 iPhone（如果你有 Mac） |

**注意：必须用 Safari 下载**。Chrome 等第三方浏览器下载的描述文件，iOS 有时不认，或者装不到正确位置。

下载后系统会提示「已下载描述文件」。

### 步骤 3：安装并信任（关键，最容易漏）

两件事，缺一不可：

**① 安装描述文件**

```
设置 → 通用 → VPN与设备管理 → 已下载的描述文件 → 安装 → 输入密码 → 安装
```

**② 开启完全信任** ⚠️

```
设置 → 通用 → 关于本机 → 证书信任设置 → 找到你的 CA → 打开开关
```

**只做第 ① 步不够**。很多人卡在这里——描述文件装了，但开关没打开，导入快捷指令仍然报「无法验证」。

### 步骤 4：构建并签名

```bash
./build/build.sh
```

构建脚本会依次做：

```
1. 校验 actions.json 注册表
2. build_pull.py 生成未签名 .shortcut
3. shortcut-sign sign 用你的 key.bin 签名
4. extract 反解比对（防止签名过程中丢动作）
4b. verify_struct.py 结构门禁（canonical + 控制流配对）
5. 复制到交付目录
6. 同步到静态站
```

产物在 `certs/<名字>-signed.shortcut`，这个就是给手机导入的文件。

### 步骤 5：交付到手机

产物在 `certs/<名字>-signed.shortcut`，把它弄到手机上就行。**没有唯一正确的方式：**

| 方式 | 说明 |
|---|---|
| **即时通讯转文件**（推荐） | QQ / 微信 / Telegram 发给自己，手机点开即导入 |
| AirDrop | 有 Mac 时最顺 |
| 网盘 / 邮件附件 | 异地、跨网络 |
| 局域网临时服务 | `python3 -m http.server` 起一下，内网访问 |
| 静态站直链 | 团队批量分发才值得，要维护域名和证书 |

**文件名用 ASCII**：中文名在某些 CDN 或 URL 编码环节会出问题。

静态站不是必需环节。`build.sh --publish` 才复制到静态站目录，默认只输出文件。

---

## 四、签名命令本身

如果你不用 `build.sh`，手工签就这一条：

```bash
env LD_LIBRARY_PATH="$PWD/lib" \
  shortcut-sign sign \
    -i out/MyShortcut.shortcut \
    -o certs/MyShortcut-signed.shortcut \
    -k certs/key.bin \
    -a certs/auth.plist
```

四个参数：

| 参数 | 作用 |
|---|---|
| `-i` | 输入：未签名文件 |
| `-o` | 输出：签名后的文件 |
| `-k` | 签名私钥（`gen-ca.sh` 生成的 `key.bin`） |
| `-a` | 签名身份数据（`auth.plist`） |

**必须带 `LD_LIBRARY_PATH`**，否则找不到 `libplist-2.0.so.4`。

### 签名后一定要验证

```bash
# 反解：签名件 → 未签名件，看动作有没有少
shortcut-sign extract -i certs/MyShortcut-signed.shortcut -o /tmp/check.shortcut

# 比对动作数
python3 -c "
import plistlib
a = plistlib.load(open('out/MyShortcut.shortcut','rb'))
b = plistlib.load(open('/tmp/check.shortcut','rb'))
print('原文件', len(a['WFWorkflowActions']), '个动作')
print('签名件', len(b['WFWorkflowActions']), '个动作')
print('一致' if len(a['WFWorkflowActions'])==len(b['WFWorkflowActions']) else '不一致 ⚠️')
"

# 看签名链信息
shortcut-sign info -i certs/MyShortcut-signed.shortcut
```

**为什么要验证**：签名过程出问题有时不报错，但签名件导入后动作莫名其妙少了一半。反解比对是唯一可靠的自检手段。

---

## 五、为什么必须用自己的证书

三个理由，都不是技术洁癖：

### ① 私钥不能共享

给你我的 `key.bin`，等于给你我的签发权。你签的东西在别人眼里就是我签的。

### ② 装 CA = 把信任根交给对方

手机装了某个 CA 并开启完全信任，意味着**这台手机信任该 CA 签发的一切**，不只是快捷指令。让别人装你的 CA，等于把他们的设备一部分控制权交给你。这不合适。

### ③ 证书有有效期

`gen-ca.sh` 默认 3650 天（10 年）。到期必须重新生成、重新装手机。共用证书的话，所有人在同一天一起失效。

---

## 六、风险与限制

自建 CA 在技术上是安全的（ECDSA P-256 + SHA-256，业界标准做法，企业内网 PKI 常用）。
**风险不在密码学，而在使用和保管。**

按严重程度排列：

| 风险 | 后果 | 应对 |
|---|---|---|
| 🔴 **私钥泄露** | 别人能签出「看起来是你发的」快捷指令，装了你的 CA 的设备会直接信任并执行 | 见下方「安全实践」第 1 条 |
| 🟠 **CA 信任范围过大** | 装了 CA 的手机信任该 CA 签发的一切（不只快捷指令），理论上可配合 DNS 劫持做中间人 | 专用 CA，不复用到别的场景；只装在测试机上 |
| 🟠 **苹果可能封堵** | iOS 大版本升级后可能整体失效 | 升级前先在备用机验证；有 Mac 就留官方签名作为后备 |
| 🟡 **证书过期** | 默认 10 年，到期不会提醒，只会突然报错 | 记下生效日期；异常时先查 `openssl x509 -noout -dates` |
| 🟡 **下载链路被篡改** | `ca.der` 在传输中被替换，你会装上攻击者的 CA | 下载后比对 sha256；或用线下方式传输 |
| 🟢 **auth.plist 身份信息** | 会暴露这个证书属于谁 | 用不含个人信息的 `--cn` / `--org` |
| 🟢 **换手机要重做** | 新设备需重新装 CA、开信任 | 保存好 `ca.der` |

### 快捷指令能做什么（为什么私钥要严格保密）

用一个恶意签名的快捷指令能做的事，比多数人想的要多：

- 读剪贴板（可能是密码、验证码）
- 读当前定位
- 发短信、发邮件
- 调用任意 URL（外传数据）
- 跑 shell 脚本（配合其他自动化）

这不是危言耸听——**这就是为什么自建 CA 的私钥等级要按「账号密码」对待**。

---

## 七、安全实践（照着做）

### 1. 私钥与目录权限

```bash
chmod 700 certs/
chmod 600 certs/ca.key certs/key.bin certs/auth.plist
```

三条硬规则：

- `certs/` 已在 `.gitignore`，**永远不提交**
- **不要通过微信 / QQ / 邮件传私钥**
- **不要放在 NAS 的共享目录**（SMB / NFS 挂载后局域网内谁都能读）

备份私钥用离线介质（U 盘、加密压缩包），别放网盘。

### 2. CA 用途隔离

**只为快捷指令建一个 CA，不要复用到 HTTPS、VPN、其他证书场景。**

`gen-ca.sh --cn "只给快捷指令用"` 就是这个意思——名字写清楚用途，别人一看就知道不该拿它签别的东西。

### 3. 下载校验

把 `ca.der` 传到手机前，先算一次哈希：

```bash
sha256sum certs/ca.der
```

手机上装完描述文件后，在「设置 → 通用 → VPN与设备管理 → 描述文件详情」里核对证书指纹。**对不上就不要信任。**

更稳的做法：用 AirDrop、U 盘这类线下方式传，完全绕开网络篡改的可能。

### 4. 验证 CA 是否真装对了

在手机的「证书信任设置」里能看到你的 CA 名称。**没出现在这个列表里，就是没装成功。**

记住：装描述文件 ≠ 信任。两步都要做。

### 5. 升级 iOS 前的验证流程

```bash
# 1. 备份当前证书
cp -a certs certs.bak.$(date +%Y%m%d)

# 2. 在备用机上测试导入
# 3. 确认能正常运行后，再升主力机
# 4. 主力机升级后再验证一次
```

### 6. 定期检查证书有效期

```bash
openssl x509 -in certs/ca.crt -noout -enddate
```

建议在日历里设个长期提醒（比如到期前 90 天），别等出错才发现。

### 7. 这台设备不要处理敏感业务

装了自建 CA 的手机，信任根已经被你改过。**不要用它登录银行、处理公司机密**——不是这个 CA 本身有问题，而是信任链已经不是出厂状态了。

---

## 八、如果你有 Mac，别折腾这套

这是最重要的一条：

**有 Mac 就用官方签名。**

```
Mac 上：快捷指令 App → 新建 → 拖入或导入 .shortcut → 自动签名 → 导出
```

优点：

- 苹果官方签名，永远不会被封
- 不用装 CA、不用开信任
- 换手机直接同步

这套自签方案的全部价值，只是**让没有 Mac 的人也能做到**。有 Mac 的话，这些折腾毫无意义。

---

## 九、一条命令速查

```bash
# 首次：生成证书
./build/gen-ca.sh --cn "我的 CA"

# 装手机：下载 certs/ca.der → 设置里安装 → 开启完全信任

# 每次改动作后：重新构建 + 签名
./build/build.sh

# 验证产物
./build/verify_struct.py out/*.shortcut
```

---

## 附：证书内容说明

`gen-ca.sh` 生成的 CA 证书包含这些扩展：

```
basicConstraints = critical, CA:TRUE      # 声明这是 CA，能签别的证书
keyUsage         = critical, keyCertSign, cRLSign   # 允许签证书、签吊销列表
```

算法：ECDSA P-256（与 `shortcut-sign` 要求一致）。

查看证书信息：

```bash
openssl x509 -in certs/ca.crt -noout -text
```
