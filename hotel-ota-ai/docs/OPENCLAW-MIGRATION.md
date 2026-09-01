# OpenClaw 生产迁移操作手册

> 适用场景：将当前服务器（47.108.200.194）的 OpenClaw + 酒店 OTA 数字员工系统整体迁移到另一台服务器。
> 核对日期：2026-08-25　|　适用对象：运维、开发
> 安全边界：本文档不记录真实密码、DSN、App Secret、Token、Encrypt Key、open_id、chat_id。

---

## 0. 文档目的与迁移范围

本文档描述**整机迁移**：把运行在源服务器的 OpenClaw 网关、酒店 OTA Chief/S14 机器人、MySQL 数据库、配置文件、系统服务迁移到目标服务器，并使新服务器对外提供完全相同的服务。

迁移范围（需整体搬迁的资产）：

| 类别 | 路径 / 资源 |
|---|---|
| OpenClaw 运行目录 | `/root/.openclaw/` |
| OpenClaw 二进制 | `/usr/local/lib/node_modules/openclaw/`（`/usr/local/bin/openclaw` 软链指向） |
| 业务工作区 | `/opt/openclaw/workspaces/hotel-ota-ai/` 与 `/opt/openclaw/workspaces/ota-marketing-diagnosis/`（含各自 `.venv/`） |
| 业务配置文件 | `/etc/hotel-ota-ai/`（`*.env` + 各 `*.json`） |
| SQLite 运行数据 | `/var/lib/hotel-ota-ai/hotel_ops.sqlite` |
| S14 报告目录 | `/var/lib/ota-marketing-diagnosis/reports/` |
| 日志目录 | `/var/log/hotel-ota-ai/` |
| Web 报告服务 | `/etc/nginx/conf.d/s14-reports.conf`（Nginx 监听 8081） |
| systemd 服务 | 见第 5 章清单 |
| MySQL 数据库 | MySQL 8.0.46 中的 `hotel_puyue`、`hotel_zhiting`、`hotel_wyn`、`hotel_pricing`、`hotel_ota_ai`、`TEST_DB`、`test2` 等 |

> ⚠️ 提示：`/root/s14-feishu-test/` 是遗留测试目录并有 `s14-feishu-bot.service` 指向它，迁移前先确认其是否仍在使用，否则可不同步。

---

## 0.1 需要保留的文件完整清单

迁移必须**整体保留**以下文件与目录。任何遗漏都会导致服务无法启动、机器人无法路由或数据权限错乱。

### A. 业务配置文件（/etc/hotel-ota-ai/）

| 文件 | 作用 | 必须 |
|---|---|---|
| `hotel-ota.env` | 全部酒店读写 DSN、飞书账号、S14 密钥前缀 | ✅ |
| `database-source.json` | hotel_id → profile → dsn_env、表名/字段映射 | ✅ |
| `feishu-role-map.json` | chief 账号归属、用户、成员关系、群绑定 bootstrap 材料 | ✅ |
| `s14-account-map.json` | S14 账号归属、回调凭据前缀 | ✅ |
| `s14-source.json` | 已注册的 S14-EXT MySQL/Excel 报告源 | ✅ |
| `market-source.json` | 酒店经纬度、天气、周边活动、区域热度 | ✅ |
| `switch-hotel.py` | 切换酒店脚本（单酒店模式用，多酒店勿直接调用） | 建议 |
| `hotel-profiles/` | 酒店 profile 目录（璞悦等） | 建议 |
| `backups/` 与 `*.bak-*` | 历史备份，可作回滚参考，非运行时必需 | 可选 |

### B. OpenClaw 运行目录（/root/.openclaw/）

| 路径 | 作用 | 必须 |
|---|---|---|
| `openclaw.json` | 飞书账号、路由 bindings、群白名单 | ✅ |
| `credentials/` | 各账号凭据（密钥，权限 700） | ✅ |
| `identity/` | 身份/网关标识 | ✅ |
| `bindings/` | 绑定状态 | ✅ |
| `feishu/` | 飞书连接状态/缓存 | ✅ |
| `agents/` `skills/` `plugins/` `extensions/` `plugin-skills/` | 代理、技能、插件定义 | ✅ |
| `memory/` `flows/` `tasks/` | 会话记忆、流程、任务状态 | ✅ |
| `cron/` `delivery-queue/` `session-delivery-queue/` | 定时任务与投递队列 | ✅ |
| `devices/` `embeddings/` `media/` `workspace/` `completions/` | 设备/向量/媒体/工作区缓存 | 建议 |
| `npm/` | openclaw npm 运行副本 | 建议 |
| `logs/` `backups/`、`openclaw.json.last-good` 及各 `.bak*` | 日志与配置回滚副本 | 可选 |

### C. SQLite 运行数据（/var/lib/hotel-ota-ai/）

| 文件 | 作用 | 必须 |
|---|---|---|
| `hotel_ops.sqlite` | **生产权威**：群绑定、成员角色、审批、任务、诊断记录 | ✅ |
| `feishu_active_auth.db` | Feishu Active Auth 后端状态 | ✅ |
| `s14/` | S14 各酒店 monthly.xlsx 与诊断报告 HTML（含 puyue/disanfang/xingfeng/reports） | ✅ |
| `s14-source-state.json` | S14 源状态 | ✅ |
| `backup/` `event-fixtures/`、`hotel_ops.sqlite.bak-*`/`.backup.2026-*` | 历史备份与测试夹具 | 可选 |

### D. S14 诊断报告目录（/var/lib/ota-marketing-diagnosis/）

| 路径 | 作用 | 必须 |
|---|---|---|
| `reports/` | 报表静态文件（含 puyue/zhiting/wyn 各酒店子目录、_templates、excel_upload） | ✅ |

### E. 业务工作区代码（/opt/openclaw/workspaces/）

| 路径 | 作用 | 必须 |
|---|---|---|
| `hotel-ota-ai/` | Chief 主链路全量代码（含 `.venv/`、`runtime/`、`scripts/`、`data/`、`config/`、`agents/`、`skills/`） | ✅ |
| `ota-marketing-diagnosis/` | S14 诊断全量代码（含 `.venv/`、`scripts/`） | ✅ |

> 两个工作区各有独立的 `.venv/` 虚拟环境，需一并迁移；若目标机器可执行环境差异导致 venv 失效，按第 7 章重建。

### F. systemd 服务定义（/etc/systemd/system/）

| 文件 | 作用 |
|---|---|
| `openclaw-gateway.service` | 生产主链路网关（✅ 必须） |
| `s14-feishu-card-callback.service` | S14 卡片回调（✅ 必须） |
| `s14-report-web.service` | 报表静态文件 HTTP（✅ 必须） |
| `s14-report-cleanup.service` | 报表清理定时任务（✅ 必须，含 `/usr/local/sbin/s14-cleanup-reports`） |
| `hotel-ota-event-bridge.service` | 事件桥接（✅ 必须） |
| `s14-feishu-bot.service` | 遗留测试服务（指向 `/root/s14-feishu-test`，⚠️ 先确认是否仍用，否则可不同步） |

### G. Nginx 配置（/etc/nginx/conf.d/）

| 文件 | 作用 |
|---|---|
| `s14-reports.conf` | 监听 8081，`/s14-reports/` 静态 + `/s14/feishu/card-callback` 代理到 127.0.0.1:8091 |

### H. OpenClaw 可执行程序

| 路径 | 作用 |
|---|---|
| `/usr/local/lib/node_modules/openclaw/` | npm 全局包（OpenClaw 主体） |
| `/usr/local/bin/openclaw` | 软链指向 `../lib/node_modules/openclaw/openclaw.mjs` |

> 建议在目标机器执行 `npm install -g openclaw@<版本>` 重建（保证原生依赖正确），或直接拷贝上述目录。版本见第 1.2 章 `openclaw --version`。

### I. MySQL 数据库与账号

**业务库（需 mysqldump 或拷贝数据目录）**：
`hotel_puyue`、`hotel_zhiting`、`hotel_wyn`、`hotel_pricing`、`hotel_ota_ai`、`TEST_DB`、`test2`

**账号（需在目标库重建并授权，见第 6.3 章）**：
`openclaw_user`（% 与 localhost）、`admin`、`hotel_control`、`hotel_puyue_read`、`hotel_puyue_write`、`hotel_puyue_task_writer_v2`、`hotel_readonly`、`hotel_ota_cp_service`、`hotel_ota_cp_migrate`、`test`

> ✏️ 导出账号清单与权限，避免漏授权：
> ```bash
> mysqldump -uroot -p --no-data mysql user db tables_priv columns_priv > /root/ota-migration/mysql-grants.sql
> # 或逐个 SHOW GRANTS FOR '<user>'@'<host>';
> ```

---

## 1. 迁移前置条件

### 1.1 目标服务器要求
- 操作系统：Linux，与源服务器同一大版本（建议同发行版）。
- 已安装：MySQL 8.0.x、Nginx、Node.js（与源服务器一致的 node/npm 版本，OpenClaw 为 npm 全局包）、Python 3（用于重建 venv）。
- 磁盘空间：估算 ≥ 5GB（openclaw 约 700MB + workspaces 约 270MB + MySQL 1.3GB + 日志余量）。

### 1.2 确认源服务器版本
```bash
# OpenClaw 版本
/usr/local/bin/openclaw --version

# Node 版本（确认 npm 全局包可重建或直接拷贝）
node --version && npm --version

# MySQL 版本
mysql --version

# 目标服务器已启用服务清单
systemctl list-units --type=service --state=running | grep -iE "hotel|openclaw|ota|s14"
```

### 1.3 停机窗口
迁移涉及数据库与运行状态，需在业务低峰期申请维护窗口；窗口内先停止写库服务再搬迁，保证 SQLite 一致性。

---

## 2. 源服务器数据备份

> 务必先在源服务器做完整备份，作为回滚点。任何包含密钥的文件不得进入 Git / 聊天工具 / 工单。

```bash
BK=/root/ota-migration-backup-$(date +%Y%m%d-%H%M%S)
mkdir -p "$BK"
chmod 700 "$BK"

# 2.1 停止写库相关服务（SQLite 一致性）
systemctl stop openclaw-gateway.service
systemctl stop s14-feishu-card-callback.service
systemctl stop hotel-ota-event-bridge.service

# 2.2 复制配置与运行数据（保留原权限）
cp -rp /root/.openclaw "$BK/openclaw"
cp -rp /etc/hotel-ota-ai "$BK/hotel-ota-ai"
cp -rp /var/lib/hotel-ota-ai "$BK/hotel-ota-ai-runtime"
cp -rp /var/lib/ota-marketing-diagnosis "$BK/ota-marketing-diagnosis"
cp -rp /var/log/hotel-ota-ai "$BK/log-hotel-ota-ai" 2>/dev/null || true

# 2.3 复制 systemd 服务定义（保留到文件，勿用 systemctl 直接改目标）
cp -p /etc/systemd/system/hotel-ota-event-bridge.service "$BK/"
cp -p /etc/systemd/system/openclaw-gateway.service "$BK/"
cp -p /etc/systemd/system/s14-feishu-bot.service "$BK/"
cp -p /etc/systemd/system/s14-feishu-card-callback.service "$BK/"
cp -p /etc/systemd/system/s14-report-cleanup.service "$BK/"
cp -p /etc/systemd/system/s14-report-web.service "$BK/"
cp -p /etc/nginx/conf.d/s14-reports.conf "$BK/"

# 2.4 导出 MySQL 全部业务库（用有权限账号；需 root 或有 GRANT/导出权）
mysqldump -uroot -p \
  --routines --triggers --single-transaction \
  --databases hotel_puyue hotel_zhiting hotel_wyn hotel_pricing hotel_ota_ai TEST_DB test2 \
  > "$BK/mysql-business.sql"

echo "备份完成: $BK"
```

> ⚠️ 备份 SQLite 时建议使用 SQLite 备份 API 或停止写入后再拷贝；不要在持续写入中直接 `cp` 并当作一致回滚件。

---

## 3. 传输到目标服务器

推荐使用含加密的通道（scp/rsync over SSH）。**禁止走明文、禁止放到公共目录。**

```bash
# 在源服务器执行（将 $BK 发往目标服务器）
rsync -avzP -e ssh "$BK" root@<目标IP>:/root/ota-migration/
```

也可使用交互式工具分两批传输（大目录用 rsync 断点续传更稳，如 `/root/.openclaw`、两个 workspaces 各 100-200MB、MySQL 数据）。

---

## 4. 目标服务器环境准备（新机器）

### 4.1 基础软件
```bash
# MySQL（须与源同 8.0.x 系列）
# package-manager 安装 mysql-server 8.0

# Nginx
# package-manager 安装 nginx

# Node.js（版本与源一致，参考 1.2 记录）
# 安装 Node + npm
npm install -g openclaw@<与源一致版本>

# Python 3（用于重建 venv）
# 安装 python3 + python3-venv
```

### 4.2 目录骨架
```bash
mkdir -p /opt/openclaw/workspaces
mkdir -p /etc/hotel-ota-ai
mkdir -p /var/lib/hotel-ota-ai
mkdir -p /var/lib/ota-marketing-diagnosis/reports
mkdir -p /var/log/hotel-ota-ai
```

---

## 5. 恢复配置文件与服务定义

### 5.1 配置文件与运行数据
```bash
cd /root/ota-migration
SRC=<实际备份目录名>

# 配置文件（保持 600/700 root:root）
cp -rp "$SRC/hotel-ota-ai"/* /etc/hotel-ota-ai/ && chmod 700 /etc/hotel-ota-ai && chmod 600 /etc/hotel-ota-ai/*

# SQLite 运行数据
cp -rp "$SRC/hotel-ota-ai-runtime"/* /var/lib/hotel-ota-ai/

# S14 报告
cp -rp "$SRC/ota-marketing-diagnosis"/* /var/lib/ota-marketing-diagnosis/

# OpenClaw 运行目录
cp -rp "$SRC/openclaw" /root/.openclaw
```

### 5.2 代码工作区
```bash
cp -rp /root/ota-migration/workspaces/hotel-ota-ai /opt/openclaw/workspaces/ 2>/dev/null || \
  scp -r <源>:/opt/openclaw/workspaces/hotel-ota-ai /opt/openclaw/workspaces/
cp -rp /root/ota-migration/workspaces/ota-marketing-diagnosis /opt/openclaw/workspaces/
```

### 5.3 systemd 服务与 Nginx
```bash
cp "$SRC/openclaw-gateway.service" /etc/systemd/system/
cp "$SRC/s14-feishu-card-callback.service" /etc/systemd/system/
cp "$SRC/s14-report-web.service" /etc/systemd/system/
cp "$SRC/s14-report-cleanup.service" /etc/systemd/system/
cp "$SRC/hotel-ota-event-bridge.service" /etc/systemd/system/
cp "$SRC/s14-feishu-bot.service" /etc/systemd/system/   # 仅在确认仍使用该测试服务时

# Nginx
cp "$SRC/s14-reports.conf" /etc/nginx/conf.d/
nginx -t && systemctl reload nginx

# 重新加载 systemd
systemctl daemon-reload
```

### 5.4 权限核对
```bash
chmod 600 /root/.openclaw/openclaw.json
chmod 600 /etc/hotel-ota-ai/*.env /etc/hotel-ota-ai/*.json
ls -la /root/.openclaw /etc/hotel-ota-ai
```

---

## 6. MySQL 数据恢复

### 6.1 导入（方式一：mysqldump 全量）
```bash
# 在目标服务器以 root 导入业务库
mysql -uroot -p < /root/ota-migration/<备份目录>/mysql-business.sql
```

### 6.2 逐库导入（方式二）
```bash
for db in hotel_puyue hotel_zhiting hotel_wyn hotel_pricing hotel_ota_ai TEST_DB test2; do
  mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS \`$db\` DEFAULT CHARACTER SET utf8mb4;"
done
mysql -uroot -p hotel_puyue < full_puyue.sql
# ... 其余库同理
```

### 6.3 还原数据库账号权限
> 需在目标 MySQL 重建源端的应用账号（如 `openclaw_user`）并授予各业务库权限。**必须给新库 `hotel_wyn` 也授权。**

```sql
-- 以目标库 root 执行
CREATE USER IF NOT EXISTS 'openclaw_user'@'%' IDENTIFIED BY '<密码>';
GRANT ALL PRIVILEGES ON hotel_puyue.* TO 'openclaw_user'@'%';
GRANT ALL PRIVILEGES ON hotel_zhiting.* TO 'openclaw_user'@'%';
GRANT ALL PRIVILEGES ON hotel_wyn.* TO 'openclaw_user'@'%';
GRANT ALL PRIVILEGES ON hotel_pricing.* TO 'openclaw_user'@'%';
GRANT ALL PRIVILEGES ON hotel_ota_ai.* TO 'openclaw_user'@'%';
GRANT ALL PRIVILEGES ON TEST_DB.* TO 'openclaw_user'@'%';
GRANT ALL PRIVILEGES ON test2.* TO 'openclaw_user'@'%';
FLUSH PRIVILEGES;

-- 验证
SHOW GRANTS FOR 'openclaw_user'@'%';
```

### 6.4 校验数据
```bash
# 逐库连接验证
mysql -uopenclaw_user -p openclaw_user ... -e "SELECT DATABASE(), COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='hotel_wyn';"
```

---

## 7. 依赖包 / venv 重建（针对目标机器可执行环境不同）

若直接拷贝 `.venv/` 失败（常见于可执行文件为绝对路径、跨发行版 glibc 差异），需重建：
```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # 依据项目实际依赖清单

cd /opt/openclaw/workspaces/ota-marketing-diagnosis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
> 优先尝试直接拷贝 `.venv`；重建是备选修复手段。执行 5.2 时记得把 `.venv` 一并带上。

---

## 8. 环境变量路径核对（关键！）

配置文件中的路径、DSN 若与源服务器不同（例如内网 IP、host 变化），必须逐项核对 `hotel-ota.env`：
```bash
grep -E "^(HOST|PORT|HOTEL_OTA_DB_DSN|S14_DB_DSN|.*_DB_DSN.*|OPENCLAW_)" /etc/hotel-ota-ai/hotel-ota.env
```
- 若新服务器 MySQL 为本地：DSN 中 host 保持 `127.0.0.1`。
- 若新服务器 MySQL 远程或端口变化：全局替换 DSN 中的 host/port。
- 任何 `*_DB_DSN_<HOTEL>` 变量不得改回默认全局值；保持多酒店精确 DSN 结构。

> ⚠️ 修改 `.env` 后需重启 `openclaw-gateway.service` 及 `s14-feishu-card-callback.service` 才生效。

---

## 9. 服务启动与冒烟测试

### 9.1 启动顺序
```bash
# 数据库已在运行的前提下
systemctl start openclaw-gateway.service
systemctl start s14-feishu-card-callback.service
systemctl start s14-report-web.service
systemctl start hotel-ota-event-bridge.service

# 状态检查
systemctl is-active openclaw-gateway.service s14-feishu-card-callback.service s14-report-web.service hotel-ota-event-bridge.service
```

### 9.2 网关日志确认多账号加载
```bash
journalctl -u openclaw-gateway.service -n 200 --no-pager | grep -iE "starting feishu|client ready|gateway.*ready|wyn|zhiting|error"
```
应看到 `default-hotel-ota-ai`、`zhiting-ota-ai`、`wyn-ota-ai`、`wyn-s14` 等账号全部 `client ready`。

---

## 10. 验证清单

### 10.1 配置文件语法
```bash
jq empty /root/.openclaw/openclaw.json
jq empty /etc/hotel-ota-ai/database-source.json
jq empty /etc/hotel-ota-ai/feishu-role-map.json
jq empty /etc/hotel-ota-ai/s14-account-map.json
jq empty /etc/hotel-ota-ai/s14-source.json
jq empty /etc/hotel-ota-ai/market-source.json
```

### 10.2 项目自检
```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
python3 scripts/validate_hotel_onboarding.py --hotel-id wyn --chief-account wyn-ota-ai --s14-account wyn-s14
```

### 10.3 业务验收（在飞书群实测）
- [ ] 各酒店群 @chief 发送"菜单"，**只有对应酒店的账号回复**（隔离验证）。
- [ ] 发送"查看当前会话绑定"，返回正确的 hotel_id。
- [ ] 发送"我的身份"，角色与 membership 一致（如 wyn owner）。
- [ ] @S14 发送"S14诊断"，报告标题、数据源均对应正确酒店。
- [ ] 跨酒店负向：新酒店小组内查询其他酒店数据被拒绝。
- [ ] 未绑定群请求业务数据被拒绝。

---

## 11. 切换流量（域名 / 回调地址）

- 若飞书机器人使用**回调模式**（非 websocket），需到飞书开放平台把事件订阅/回调地址更新为新服务器地址。
- 若使用 **websocket 长连接模式**，无需改飞书侧，新机器自然接管。
- 若有对外域名，DNS 将 A 记录指向新服务器 IP。

---

## 12. 回滚方案

```bash
# 在目标服务器有异常，回退到源服务器运行（此时源服务器已按第 2 章停机）
systemctl start openclaw-gateway.service   # 在源服务器
systemctl start s14-feishu-card-callback.service
```

若需要回滚到"迁移前完整状态"（目标服务器改坏了），用第 2 章备份的 `$BK` 反向覆盖恢复，再按第 9、10 章重测。
> 回滚前确认没有新写入的数据落库到 MySQL；否则回滚会丢失新数据，需评估业务影响。

---

## 13. 变更单最终签字项

- [ ] 变更编号、操作人、时间窗口已记录。
- [ ] 真实密钥仅存在于私有配置，未进入 Git / 聊天 / 工单。
- [ ] 源服务器备份完成并验证可回滚。
- [ ] 目标服务器软件版本与源一致（OpenClaw、Node、MySQL、Nginx）。
- [ ] 配置文件语法通过、权限正确。
- [ ] MySQL 全库导入成功，`openclaw_user` 对全部业务库有权限。
- [ ] 网关日志显示全部飞书账号 client ready，无报错。
- [ ] 各酒店正向业务链路验收通过。
- [ ] 跨酒店 / 未绑定群的拒绝测试通过。
- [ ] 回调地址（如适用）已切换到新服务器。
- [ ] 日志无密钥、DSN 和跨酒店数据泄露。