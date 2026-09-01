# OpenClaw 酒店数字员工 · 服务器更换备份清单

> 适用项目：`hotel-ota-ai`（酒店 OTA 营销诊断数字员工）
> 当前服务器：阿里云 ECS（hostname 见 `hostname` 命令）
> OpenClaw 版本：2026.5.28
> systemd 服务：`openclaw-gateway`（端口 18789）

---

## 一、备份优先级总览

| 优先级 | 类别 | 说明 | 丢了会怎样 |
|---|---|---|---|
| **P0 — 敏感凭证** | API Key、密码、Token、OAuth 凭证 | 必须加密备份，**严禁明文传输到公网** | 服务完全无法启动，且有安全风险 |
| **P1 — 业务配置 + 运行时数据** | 酒店档案、数据库源映射、Agent 会话、记忆库 | 直接决定业务能否正常运行 | 服务能启动但无业务数据，所有历史会话丢失 |
| **P2 — 项目代码 + Skills** | 代码仓库、Python runtime、技能定义、路由 | 可从 Git 重新 clone，但本地改动会丢 | 需要重新部署，定制 patches 会丢失 |
| **P3 — 可重装依赖** | OpenClaw 框架本体、node_modules、.venv、日志 | 可用 npm/pip 重新安装 | 重装即可恢复 |

---

## 二、P0 · 敏感凭证（必须加密备份）

### 2.1 业务级密钥

| 文件路径 | 内容 | 备份建议 |
|---|---|---|
| `/etc/hotel-ota-ai/hotel-ota.env` | 全部 API Key / DB 密码 / LLM 模型密钥（含通义、DeepSeek、微信等） | 🔐 用 GPG 加密后再传输 |
| `/etc/hotel-ota-ai/database-source.json` | 数据库连接串（含各酒店 DB 的 host/user/password） | 🔐 加密 |

### 2.2 OpenClaw 核心凭证

| 文件路径 | 内容 | 备份建议 |
|---|---|---|
| `/root/.openclaw/openclaw.json` | 含 gateway token + skill 配置 + 通道配置 | 🔐 提取后加密 |
| `/home/admin/.openclaw/openclaw.json` | admin 用户 gateway token + feishu 插件配置 | 🔐 提取后加密 |
| `/home/admin/.openclaw/credentials/lark.secrets.json` | 飞书 OAuth App Secret + Token | 🔐 **这个丢了飞书要重新授权** |

### 2.3 加密备份示例

```bash
# 对 P0 文件整体加密打包（需要先在两台机器上交换 GPG 公钥）
gpg --symmetric --cipher-algo AES256 \
  -o p0-secrets.tar.gz.gpg \
  -c \
  /etc/hotel-ota-ai/hotel-ota.env \
  /etc/hotel-ota-ai/database-source.json \
  /root/.openclaw/openclaw.json \
  /home/admin/.openclaw/openclaw.json \
  /home/admin/.openclaw/credentials/lark.secrets.json
```

---

## 三、P1 · 业务配置与运行时数据

### 3.1 系统级业务配置目录（整个目录整体备份）

```bash
# 整个 /etc/hotel-ota-ai/ 目录打包
tar czf p1-etc-hotel-ota-ai.tar.gz /etc/hotel-ota-ai/
```

内含文件清单：

| 文件 | 大小 | 说明 |
|---|---|---|
| `hotel-ota.env` | — | ⚠️ 已归入 P0 |
| `database-source.json` | 28K | ⚠️ 已归入 P0 |
| `feishu-role-map.json` | 5K | 飞书角色→权限映射，**必须与飞书 App 配置一致** |
| `market-source.json` | 9.7K | 外部市场数据源配置 |
| `s14-account-map.json` | 1.2K | S14 诊断账号映射 |
| `s14-source.json` | 920B | S14 数据源配置 |
| `hotel-profiles/` | 目录 | 各酒店档案（酒店信息、品牌、归属等） |
| `switch-hotel.py` | 33K | 酒店切换辅助脚本 |
| `backups/` | 目录 | 系统自动备份历史，**可不备份，只用最新的** |

### 3.2 OpenClaw root 用户运行时（整个目录）

```bash
# 打包 /root/.openclaw/（注意排除已归入 P0 的 openclaw.json，或一起打包后加密）
tar czf p1-root-openclaw-runtime.tar.gz \
  --exclude='openclaw.json' \
  --exclude='extensions/openclaw-lark/' \
  --exclude='npm/' \
  --exclude='embeddings/' \
  /root/.openclaw/
```

关键子目录：

| 路径 | 大小 | 说明 | 是否必须 |
|---|---|---|---|
| `agents/` | 311M | 各 Agent 会话 `.jsonl` + `.trajectory.jsonl` + `sessions.json` | ✅ 必须（历史会话记录） |
| `embeddings/` | 314M | 向量嵌入缓存 | ⚡ 可重建，但重生成很慢，建议备份 |
| `memory/main.sqlite` | — | Agent 长期记忆库 | ✅ 必须（丢了 AI 会失忆） |
| `tasks/runs.sqlite` | — | Cron 定时任务执行记录 | ✅ 必须 |
| `skills/` | 644K | 自定义 Skill 本地副本 | ✅ 必须 |
| `workspace/` | 164K | Workspace 运行时状态 | ✅ 必须 |
| `media/` | 9.3M | 图片/媒体缓存 | ⚡ 可丢 |
| `feishu/` | 48K | 飞书运行时数据 | ✅ 必须 |
| `plugins/installs.json` | — | 插件安装记录 | ✅ 必须 |
| `identity/device*.json` | — | 设备身份 | ✅ 必须（gateway 绑定） |
| `devices/*.json` | — | 已配对设备 | ✅ 必须 |
| `extensions/openclaw-lark/` | — | 飞书插件源码 | ⚡ 可重装，但建议备份省时间 |
| `npm/` | 49M | OpenClaw npm 包缓存 | ⚡ 可丢，重新 npm install |
| `logs/` | 152K | 日志 | ⚡ 可丢 |
| `backups/` | 16K | 自动备份 | ⚡ 可丢 |

### 3.3 OpenClaw admin 用户运行时

```bash
tar czf p1-admin-openclaw-runtime.tar.gz \
  --exclude='openclaw.json' \
  --exclude='credentials/lark.secrets.json' \
  --exclude='extensions/openclaw-lark/' \
  --exclude='npm/' \
  /home/admin/.openclaw/
```

> admin 用户下的 `openclaw-weixin/`（微信插件）、`workspace/memory/`、`agents/main/` 会话都是独立运行的，按需备份。

---

## 四、P2 · 项目代码与 Skills

### 4.1 主项目（hotel-ota-ai）

```bash
# 先停服务
systemctl stop openclaw-gateway

# 整个项目打包（排除 .venv，venv 归入 P3）
tar czf p2-hotel-ota-ai-code.tar.gz \
  --exclude='.venv/' \
  --exclude='.git/' \
  /opt/openclaw/workspaces/hotel-ota-ai/
```

为什么排除 `.git/`：Git 仓库可远程拉取，若本地提交了未推送的 commit 则**不要排除 .git/**。

### 4.2 副项目（ota-marketing-diagnosis）

```bash
tar czf p2-ota-marketing-diagnosis.tar.gz \
  --exclude='.venv/' \
  --exclude='.git/' \
  /opt/openclaw/workspaces/ota-marketing-diagnosis/
```

### 4.3 代码核心子目录清单（hotel-ota-ai）

| 路径 | 说明 |
|---|---|
| `agents/` | A0~A6 六个 Agent 角色定义 |
| `architecture/` | 节点注册表、合约、算法覆盖矩阵 |
| `config/` | 配置模板（`.example` 文件） |
| `contracts/` + `contracts/v26/` + `contracts/v27/` | 数据字段合约（版本化） |
| `runtime/` | Python 运行时（算法、Feishu 路由、s13~s17 能力） |
| `skills/hotel-ota/` | 14 个业务 Skill（s01~s16） |
| `router/` | 场景路由表 |
| `ops/` | 运维脚本 |
| `docs/` / `docs_dev/` | 架构文档 |
| `cron/setup-cron.sh` | 定时任务安装脚本 |

### 4.4 systemd 服务文件

```bash
cp /etc/systemd/system/openclaw-gateway.service p2-openclaw-gateway.service
```

---

## 五、P3 · 可重新安装的依赖（不强制备份）

| 路径 | 说明 | 重装命令 |
|---|---|---|
| `/usr/local/lib/node_modules/openclaw/` | OpenClaw 框架本体 | `npm install -g openclaw` 或 `npm install -g openclaw@2026.5.28` |
| `/usr/local/bin/openclaw` | CLI 符号链接 | 随 npm 全局安装自动创建 |
| `/opt/openclaw/workspaces/hotel-ota-ai/.venv/` | Python 虚拟环境 | 新项目上执行 `python -m venv .venv && pip install -r pyproject.toml` |
| `/opt/openclaw/workspaces/ota-marketing-diagnosis/.venv/` | 同上 | 同上 |
| `/home/admin/.openclaw/extensions/openclaw-lark/` | 飞书插件 | 可通过 `openclaw plugin install` 重新安装 |
| `/home/admin/.openclaw/openclaw-weixin/` | 微信插件 | 可重新 clone |
| `/opt/agent-sec/openclaw-plugin/` | 安全插件 | 跟随 OpenClaw 重装 |
| `/var/log/openclaw*.log` | 网关日志 | 自动生成，可丢 |
| `/tmp/openclaw*/` | 临时目录 | 自动清理 |

> 💡 **省时建议**：如果网络慢，可以把 `.venv/` 和 `openclaw` npm 包也拷走省得重装，毕竟 `.venv` 只有几百 MB。

---

## 六、容易遗漏的项目

### 6.1 Cron 定时任务

```bash
# root 用户有一条每日重启
crontab -l
# 输出：0 8 * * * /bin/systemctl restart openclaw-gateway.service

# openclaw cron 内置定时任务（需要在新服务器上重新创建）
openclaw cron list
# 已安装：S15 每日销售基线（07:30）、S16 小时偏差诊断（每小时 12 分）
```

> `openclaw cron` 内置任务存储在 `/root/.openclaw/cron/`，已经归入 P1 备份范围。但**建议到新服务器上用 `openclaw cron list` 核对一下**。

### 6.2 用户与用户组

```bash
id root          # 服务以 root 运行
id admin         # admin 用户也有独立的 OpenClaw 配置
getent group hotel-ota 2>/dev/null  # 系统级组
```

### 6.3 Shell Profile 中的环境变量

```bash
grep -r "openclaw\|HOTEL_OTA\|DEEPSEEK\|FEISHU" /etc/profile /etc/environment /root/.bashrc /home/admin/.bashrc 2>/dev/null
```

### 6.4 Nginx / 反向代理配置（如果有）

```bash
# 检查是否有反代
ls /etc/nginx/sites-enabled/ 2>/dev/null
grep -r "18789\|11878" /etc/nginx/ 2>/dev/null
```

---

## 七、一键备份命令（在旧服务器上执行）

```bash
#!/usr/bin/env bash
# openclaw-backup.sh — 旧服务器上执行
set -euo pipefail

STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_ROOT="/root/openclaw-backup-${STAMP}"
mkdir -p "$BACKUP_ROOT"

echo "=== [1/5] 停止服务 ==="
systemctl stop openclaw-gateway || true

echo "=== [2/5] P0 敏感凭证（加密） ==="
tar czf - \
  /etc/hotel-ota-ai/hotel-ota.env \
  /etc/hotel-ota-ai/database-source.json \
  /root/.openclaw/openclaw.json \
  /home/admin/.openclaw/openclaw.json \
  /home/admin/.openclaw/credentials/lark.secrets.json \
  | gpg --symmetric --cipher-algo AES256 \
       -o "$BACKUP_ROOT/p0-secrets.tar.gz.gpg"

echo "=== [3/5] P1 业务配置 + 运行时数据 ==="
tar czf "$BACKUP_ROOT/p1-etc-hotel-ota-ai.tar.gz" /etc/hotel-ota-ai/

tar czf "$BACKUP_ROOT/p1-root-openclaw-runtime.tar.gz" \
  --exclude='openclaw.json' \
  --exclude='npm/' \
  /root/.openclaw/

tar czf "$BACKUP_ROOT/p1-admin-openclaw-runtime.tar.gz" \
  --exclude='openclaw.json' \
  --exclude='credentials/lark.secrets.json' \
  --exclude='npm/' \
  /home/admin/.openclaw/

echo "=== [4/5] P2 项目代码 + systemd ==="
tar czf "$BACKUP_ROOT/p2-hotel-ota-ai.tar.gz" \
  --exclude='.venv/' --exclude='.git/' \
  /opt/openclaw/workspaces/hotel-ota-ai/

tar czf "$BACKUP_ROOT/p2-ota-marketing-diagnosis.tar.gz" \
  --exclude='.venv/' --exclude='.git/' \
  /opt/openclaw/workspaces/ota-marketing-diagnosis/

cp /etc/systemd/system/openclaw-gateway.service "$BACKUP_ROOT/p2-openclaw-gateway.service"
crontab -l > "$BACKUP_ROOT/p2-root-crontab.txt"

echo "=== [5/5] P3 可重装依赖（省时包，可选） ==="
tar czf "$BACKUP_ROOT/p3-venvs.tar.gz" \
  /opt/openclaw/workspaces/hotel-ota-ai/.venv/ \
  /opt/openclaw/workspaces/ota-marketing-diagnosis/.venv/
tar czf "$BACKUP_ROOT/p3-openclaw-framework.tar.gz" \
  /usr/local/lib/node_modules/openclaw/

echo "=== [6/6] 完整性校验 ==="
cd "$BACKUP_ROOT"
sha256sum * > SHA256SUMS.txt
for f in *.tar.gz; do
  tar -tzf "$f" > /dev/null && echo "  ✅ $f OK" || echo "  ❌ $f 损坏"
done
# GPG 文件也要校验（不解密，只做 hash 校验）
sha256sum *.gpg >> SHA256SUMS.txt

echo ""
echo "✅ 备份完成：$BACKUP_ROOT"
ls -lh "$BACKUP_ROOT"
du -sh "$BACKUP_ROOT"

echo ""
echo "=== 恢复到新服务器的步骤 ==="
echo "1. scp $BACKUP_ROOT/*  新服务器:/tmp/openclaw-backup/"
echo "2. 在新服务器上 cd /tmp/openclaw-backup && sha256sum -c SHA256SUMS.txt"
echo "3. 运行 openclaw-restore.sh"
```

---

## 八、恢复步骤（在新服务器上执行）

```bash
#!/usr/bin/env bash
# openclaw-restore.sh — 新服务器上执行
set -euo pipefail

BACKUP="/tmp/openclaw-backup-YYYYMMDD_HHMMSS"  # ⚠️ 改成实际目录

# ---- 0. 安装基础依赖 ----
apt update && apt install -y nodejs npm python3 python3-venv python3-pip
npm install -g openclaw@2026.5.28

# ---- 1. 恢复 P0 敏感凭证 ----
# 先解密（会要求输入加密密码）
gpg --decrypt "$BACKUP/p0-secrets.tar.gz.gpg" | tar xzf - -C /

# ---- 2. 恢复 P1 业务配置 + 运行时 ----
tar xzf "$BACKUP/p1-etc-hotel-ota-ai.tar.gz" -C /
tar xzf "$BACKUP/p1-root-openclaw-runtime.tar.gz" -C /
tar xzf "$BACKUP/p1-admin-openclaw-runtime.tar.gz" -C /

# ---- 3. 恢复 P2 项目代码 ----
mkdir -p /opt/openclaw/workspaces
tar xzf "$BACKUP/p2-hotel-ota-ai.tar.gz" -C /opt/openclaw/workspaces/
tar xzf "$BACKUP/p2-ota-marketing-diagnosis.tar.gz" -C /opt/openclaw/workspaces/
cp "$BACKUP/p2-openclaw-gateway.service" /etc/systemd/system/

# ---- 4. 恢复 P3 依赖（如果备份了） ----
if [ -f "$BACKUP/p3-venvs.tar.gz" ]; then
  tar xzf "$BACKUP/p3-venvs.tar.gz" -C /
else
  echo ">>> 重新创建 Python venv..."
  cd /opt/openclaw/workspaces/hotel-ota-ai
  python3 -m venv .venv && source .venv/bin/activate && pip install -e .
fi

# ---- 5. 设置权限 ----
chown -R root:root /opt/openclaw /etc/hotel-ota-ai /root/.openclaw
chown -R admin:admin /home/admin/.openclaw

# ---- 6. 启用 systemd ----
systemctl daemon-reload
systemctl enable --now openclaw-gateway

# ---- 7. 恢复 Cron ----
crontab /tmp/openclaw-backup-*/p2-root-crontab.txt

# ---- 8. 验证 ----
sleep 5
systemctl status openclaw-gateway --no-pager
openclaw cron list
openclaw health 2>/dev/null || openclaw gateway status
```

---

## 九、迁移后验证清单

- [ ] `systemctl status openclaw-gateway` 显示 **active (running)**
- [ ] 飞书 Bot 能正常收发消息（发一条 `/help` 测试）
- [ ] `openclaw cron list` 显示 S15/S16 定时任务
- [ ] `openclaw health` 全部检查通过
- [ ] 运行 `/skill s02-operating-snapshot` 验证数据库连接正常
- [ ] 检查飞书 OAuth 是否重新授权（旧 Token 可能失效）
- [ ] 检查防火墙端口 18789 是否开放
- [ ] `crontab -l` 确认每日重启任务存在
- [ ] `journalctl -u openclaw-gateway -f` 观察 5 分钟无报错

---

## 十、快速参考：哪些可以丢，哪些不能丢

```
✅ 必须备份（丢了业务挂）
├── /etc/hotel-ota-ai/           ← 整个目录
├── /root/.openclaw/openclaw.json
├── /root/.openclaw/memory/main.sqlite
├── /root/.openclaw/agents/      ← 会话记录
├── /root/.openclaw/tasks/runs.sqlite
├── /root/.openclaw/feishu/
├── /home/admin/.openclaw/openclaw.json
├── /home/admin/.openclaw/credentials/lark.secrets.json
├── /home/admin/.openclaw/openclaw.json
├── /etc/systemd/system/openclaw-gateway.service
└── crontab -l 内容

⚡ 建议备份（可重建但耗时）
├── /opt/openclaw/workspaces/hotel-ota-ai/  ← 排除 .venv 和 .git
├── /opt/openclaw/workspaces/ota-marketing-diagnosis/
├── /root/.openclaw/embeddings/  ← 314M 向量缓存
├── /home/admin/.openclaw/extensions/openclaw-lark/
└── .venv/ 两个项目的 Python 虚拟环境

🗑️ 不用备份（可重新安装）
├── /usr/local/lib/node_modules/openclaw/  ← npm i -g openclaw
├── /opt/agent-sec/openclaw-plugin/
├── /var/log/openclaw*.log
├── /tmp/openclaw*/
├── .git/    目录（git pull 即可）
├── node_modules/（在 openclaw-lark 下）
└── openclaw 自动生成的 backups/ 目录
```

---

## 十一、⚠️ 迁移前必须做的事（容易忘）

### 11.1 把这份文档单独拷出来

> 这份 md 文档本身位于 `/opt/openclaw/workspaces/hotel-ota-ai/ops/`，在 P2 备份包里。但**建议先单独 scp 到你本地电脑**，作为操作指南在手边。

```bash
# 在本地电脑执行
scp root@旧服务器IP:/opt/openclaw/workspaces/hotel-ota-ai/ops/server-migration-backup-checklist.md ./
```

### 11.2 更新 IP 白名单（迁移前先查好新服务器 IP）

| 需要更新的地方 | 操作 | 怎么查 |
|---|---|---|
| **酒店数据库白名单** | 把新服务器公网 IP 加入 MySQL 白名单 | 让 DBA 在 `mysql.user` 中添加 |
| **飞书 Webhook 回调地址** | 新服务器 IP + 端口需更新飞书后台的事件订阅 URL | 飞书开放平台 → 应用 → 事件订阅 |
| **LLM API 提供商 IP 限制** | 通义/DeepSeek/阿里云等 API 是否有出口 IP 限制 | 查看各平台控制台的安全设置 |
| **酒店 OTA 后台 IP 白名单** | 美团/点评/携程等后台可能绑定 API 调用 IP | 登录各 OTA 商家后台查 |
| **防火墙/安全组** | 开放 18789（openclaw gateway）、SSH 端口 | 阿里云安全组控制台 |
| **反向代理 Nginx**（如果有） | 更新 upstream 到新 IP | `/etc/nginx/sites-enabled/` |

### 11.3 加密密码管理

GPG 对称加密用的密码请：
- ✅ 存到 1Password / Bitwarden / 密码管理器
- ✅ 用至少 20 位的随机密码
- ❌ 不要写在聊天记录或邮件里
- ❌ 不要用简单密码

恢复时需要：`gpg --decrypt p0-secrets.tar.gz.gpg | tar xzf - -C /`

---

## 十二、故障排查速查

| 现象 | 可能原因 | 排查 |
|---|---|---|
| `systemctl start` 失败 | `.env` 文件权限不对 / DB 连不上 | `journalctl -u openclaw-gateway -n 100` |
| 飞书 Bot 无响应 | OAuth Token 过期 / 回调 URL 未更新 | `openclaw plugin feishu doctor` |
| Cron 任务不跑 | `openclaw cron list` 为空 | 确认 `/root/.openclaw/cron/` 恢复了，或重新 `openclaw cron add` |
| 数据库连接失败 | 新服务器 IP 未加白名单 | 让 DBA 检查 DB 侧白名单 |
| Agent 会话没历史 | `/root/.openclaw/agents/` 没恢复全 | 检查 tar 包完整性 |
| Gateway token 冲突 | root 和 admin 各有一个 openclaw.json | 当前 systemd 以 root 运行，用的是 `/root/.openclaw/openclaw.json` |

---

*文档生成时间：2026-08-31 · 基于服务器实际扫描结果整理*
