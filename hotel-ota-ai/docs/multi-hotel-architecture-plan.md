# 多酒店同时在线方案（一酒店两机器人：主收益助手 + S14诊断助手，技能/运行时共享）

> 编写日期：2026-08-23
> 更新日期：2026-08-23（补充S14机器人多酒店支持）
> 目标场景：多个酒店同时在线，每个酒店有**两个**飞书机器人（主收益助手 + S14营销诊断助手），各自有飞书群，互不干扰，/opt下的skills和runtime代码共用一套

---

## 一、现状分析

### 1.1 当前架构（双机器人模型）

系统实际上有**两个独立的OpenClaw Agent**，各自处理不同职责：

```
OpenClaw Gateway (单进程)
  │
  ├── agent: hotel-ota-chief                    ← 主收益助手
  │     workspace: /opt/openclaw/workspaces/hotel-ota-ai/
  │     ├── skills/hotel-ota/s01~s17/           ← 调价/快照/促销/评论/审批/内部S14等
  │     ├── runtime/                             ← Python运行时（认证/DB/路由/安全）
  │     ├── plugin: hotel-ota-feishu-auth        ← 飞书认证拦截插件
  │     └── 配置从 /etc/hotel-ota-ai/ 读取（单酒店）
  │
  └── agent: s14-operation-diagnosis            ← S14营销诊断助手（独立workspace）
        workspace: /opt/openclaw/workspaces/ota-marketing-diagnosis/
        ├── marketing_diagnosis/                 ← S14核心诊断逻辑
        ├── skills/s14-operation-diagnosis/      ← S14 OpenClaw skill封装
        ├── scripts/s14_feishu_entry.py          ← 飞书入口（状态机/触发词/DSN选择）
        ├── scripts/s14_feishu_card_callback.py  ← 卡片按钮回调HTTP服务
        └── 环境变量: S14_DB_DSN（单DSN硬编码默认puyue）
```

**飞书账号现状**（`openclaw.json` channels.feishu.accounts）：

| accountId | 路由到agent | 用途 |
|-----------|------------|------|
| default-hotel-ota-ai | hotel-ota-chief | 璞悦主收益机器人 |
| hotel-ota-ai-test | hotel-ota-chief | 测试机器人 |
| s14-ext | s14-operation-diagnosis | 璞悦S14诊断机器人 |
| s14-ext-test | s14-operation-diagnosis | S14测试机器人 |

**问题**：两个agent都只能服务一个酒店配置，换酒店要改配置、重启。

### 1.2 已天然支持多酒店的组件

| 组件 | 文件位置 | 多酒店支持度 |
|------|----------|-------------|
| OpenClaw 飞书多账号 | `openclaw.json` channels.feishu.accounts | ✅ 原生支持 |
| Bindings 按 accountId 路由 | `openclaw.json` bindings 按 accountId 路由到不同agent | ✅ 原生支持 |
| feishu-role-map.json v3 | group_chat_bindings/hotel_memberships 按 hotel_id 区分 | ✅ 原生支持 |
| SQLite auth 表含 hotel_id | runtime/storage.py 多张表已有 hotel_id 字段 | ✅ 原生支持 |
| market-source.json hotels{} | runtime/market_sources.py 按 hotel_id 索引 | ✅ 原生支持 |
| s14-source.json hotels{} | runtime/s14_source_registry.py 按 hotel_id 索引 | ✅ 原生支持 |
| database-source.json profiles{} | 支持多profile + inherits继承 | ✅ 结构支持 |
| build_auth_context | runtime/safety/auth.py 解析 resolved_hotel_id | ✅ 原生支持 |
| S14报告目录按hotel分段 | S14 skill _report_dir() 已有 hotel/platform/period/run_id 路径 | ✅ 原生支持 |
| S14状态文件按chat_id隔离 | s14_feishu_entry.py STATE_DIR 用 chat_id+sender_id 命名 | ✅ 天然隔离 |

### 1.3 需要改造的关键卡点

**主收益助手 (hotel-ota-chief)：**

| # | 卡点 | 位置 | 问题描述 | 严重度 |
|---|------|------|----------|--------|
| ① | 插件账号数硬限制 | ops/.../hotel-ota-feishu-auth/index.mjs:14 | targetAccounts() 要求"exactly two"，需改为≥1 | 🔴高 |
| ② | DB profile 全局选择（3处重复！） | database.py:571, nearby_events.py:46, hourly_history.py:32 | **3个文件都有独立的 _profile() 副本**，全部用 `HOTEL_OTA_DB_PROFILE` 环境变量或 `default_profile` 选profile，都不支持 hotel_id→profile 映射 | 🔴高 |
| ③ | DSN回退链全部落到璞悦 | database.py:592-600(_dsn_from_args), nearby_events.py:55-57, hourly_history.py:43-45 | DSN查找链：profile.dsn_env → **HOTEL_OTA_DB_DSN（全局=璞悦）** → profile.dsn，当hotel_id对应的profile未正确解析时，**必然回退连璞悦库** | 🔴高 |
| ④ | **S8促销展示硬编码回退璞悦** | s08_promotion_display_source.py:87-89 | `S8PromotionDisplayMySQLSource.from_env()` 直接 `or os.environ.get("HOTEL_OTA_DB_DSN_PUYUE")`，**完全绕过profile系统**，调用处 `query_s8_promotion_display()` 虽然传了hotel_id但from_env()不用它来选DSN | 🔴高 |
| ⑤ | **S9流量转化硬编码回退璞悦** | s09_traffic_conversion_real.py:476-484 | `S09MySQLSource.from_env()` 同样 `or os.environ.get("HOTEL_OTA_DB_DSN_PUYUE")`，调用处 `build_s09_report(source=S09MySQLSource.from_env())` **无参调用，直接连璞悦** | 🔴高 |
| ⑥ | **S10促销ROI硬编码回退璞悦** | s10_promotion_source.py:71-74 | `S10MySQLSource.from_env()` 同样 `or os.environ.get("HOTEL_OTA_DB_DSN_PUYUE")`，调用处 `query_s10_promotion_performance(source=source or S10MySQLSource.from_env())` **无参调用** | 🔴高 |
| ⑦ | **S11促销执行控制硬编码回退璞悦** | s11_promotion_execution_patch.py:178-181 | `_promotion_control_dsn()` 直接 `or os.environ.get("HOTEL_OTA_DB_DSN_PUYUE")`，促销写入操作连错库会**直接改其他酒店数据** | 🔴高 |
| ⑧ | **S12口碑报告硬编码回退璞悦** | s12_reputation_real.py:278-281 | `S12MySQLSource.from_env()` 回退链：S12_SOURCE_DSN → **HOTEL_OTA_DB_DSN_PUYUE** → S13_SOURCE_DSN，调用处 `S12MySQLSource.from_env()` 无参调用 | 🔴高 |
| ⑨ | **S13评论数据源硬编码回退璞悦** | s13/source.py:260-263 | `MySQLReviewSourceRepository.from_env()` 回退到 `HOTEL_OTA_DB_DSN_PUYUE`；s13/task_outbox.py:325 `MySQLReviewTaskOutbox.from_env()` 使用全局 `HOTEL_OTA_REVIEW_TASK_DSN`（单值=璞悦） | 🔴高 |
| ⑩ | 调价任务DSN全局单值 | s6_fast_outbox_guard.py:108-111, pricing.py:1168-1170, zhiting_price_task_outbox.py:121 | 调价任务出站使用 `HOTEL_OTA_PRICE_TASK_DB_DSN`（单值=璞悦），回退到 `HOTEL_OTA_DB_DSN`（璞悦） | 🔴高 |
| ⑪ | 评论任务DSN全局单值 | hotel-ota.env:92, s13/task_outbox.py:325 | `HOTEL_OTA_REVIEW_TASK_DSN` 单值=璞悦，评论回复写入会写错库 | 🔴高 |
| ⑫ | SQLite 路径全局 | runtime/common.py:15 | DEFAULT_DB 单一路径（决策：全局共用一个DB，通过hotel_id字段隔离） | 🟡中 |
| ⑬ | 日志/经验目录全局 | runtime/common.py, experience_store.py | 路径硬编码，不按酒店区分 | 🟡中 |
| ⑭ | 插件不传递 accountId | lib/auth_ingress.mjs route() | 未将 accountId 传给 Python | 🟡中 |
| ⑮ | 配置路径硬编码 | market_sources.py, s14_source_registry.py | DEFAULT_*_CONFIG 路径（已有env覆盖能力） | 🟢低 |

> **⚠️ 关键发现**：S8~S13共6个技能**完全绕过了 database.py 的profile映射系统**，各自维护独立的MySQL连接类，且 `from_env()` 方法全部硬编码回退到 `HOTEL_OTA_DB_DSN_PUYUE`。如果不改造这些模块，即使修好了 _profile() 的hotel_id路由，这些技能仍然会读到璞悦的数据！而且S11（促销执行）和S13（评论回复）是**写入操作**，连错库会直接篡改其他酒店数据。

**S14诊断助手 (s14-operation-diagnosis)：**

| # | 卡点 | 位置 | 问题描述 | 严重度 |
|---|------|------|----------|--------|
| ⑯ | S14 DSN单一硬编码 | s14_feishu_entry.py _config() | 只使用 `S14_DB_DSN` 单个环境变量，默认连puyue | 🔴高 |
| ⑰ | S14 hotel_id硬编码 | s14_feishu_entry.py _hotel()/HOTEL_ALIASES, skill __init__.py _prepare_inputs() | 酒店别名硬编码，默认"puyue" | 🔴高 |
| ⑱ | S14不接收accountId | s14_feishu_entry.py CLI参数 | 无 --account-id 参数，无法从飞书账号定位酒店 | 🟡中 |
| ⑲ | S14卡片回调单租户 | s14_feishu_card_callback.py create_app() | 只支持单个 FEISHU_APP_ID/SECRET，无法处理多酒店卡片回调 | 🔴高 |
| ⑳ | S14 Skill DSN回退 | skill __init__.py _resolve_dsn() | DSN回退链也只到 S14_DB_DSN 单值 | 🟡中 |

---

## 二、目标架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      OpenClaw Gateway (单进程)                                │
│                                                                             │
│  channels.feishu.accounts (每个酒店2个账号):                                  │
│                                                                             │
│  ┌─ 璞悦 ──────────────────────┐  ┌─ 酒店A ─────────────────────┐            │
│  │ 🏨 璞悦收益助手              │  │ 🏨 酒店A收益助手             │            │
│  │ accountId: puyue-chief      │  │ accountId: hotela-chief     │            │
│  │ (default-hotel-ota-ai)      │  │                             │            │
│  │                              │  │                              │            │
│  │ 📊 璞悦S14诊断助手           │  │ 📊 酒店A S14诊断助手         │            │
│  │ accountId: puyue-s14        │  │ accountId: hotela-s14       │            │
│  │ (s14-ext)                   │  │                             │            │
│  └──────────────────────────────┘  └─────────────────────────────┘            │
│         │              │                   │              │                   │
│         ▼              ▼                   ▼              ▼                   │
│  bindings: accountId → agentId                                               │
│  puyue-chief  ──────→ hotel-ota-chief  (同一个agent)                          │
│  hotela-chief ──────→ hotel-ota-chief  (同一个agent)                          │
│  puyue-s14    ──────→ s14-operation-diagnosis (同一个agent)                   │
│  hotela-s14   ──────→ s14-operation-diagnosis (同一个agent)                   │
│                                                                             │
│  ┌─ 主收益助手插件 ──────────────────────────────────────────────────────┐   │
│  │ hotel-ota-feishu-auth (改造后)                                        │   │
│  │ - 拦截所有 *-chief 账号的消息（不拦截s14账号）                          │   │
│  │ - 传递 accountId 给 Python                                            │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
┌─────────────────────────────┐            ┌─────────────────────────────────────┐
│  hotel-ota-chief Agent      │            │  s14-operation-diagnosis Agent      │
│  (共享，单套代码，零复制)      │            │  (共享，单套代码，零复制)              │
│                             │            │                                     │
│  /opt/openclaw/workspaces/  │            │  /opt/openclaw/workspaces/          │
│    hotel-ota-ai/            │            │    ota-marketing-diagnosis/         │
│                             │            │                                     │
│  关键能力:                    │            │  关键能力:                           │
│  1. resolve_hotel_id()      │            │  1. resolve_hotel_id()              │
│  2. resolve_db_profile()    │            │  2. resolve_s14_dsn()               │
│  3. hotel_scoped_paths()    │            │  3. hotel_scoped_report_dir()       │
│                             │            │  4. multi-tenant card callback      │
│  执行链路:                    │            │                                     │
│  accountId/chatId           │            │  执行链路:                           │
│    → hotel_id               │            │  accountId/chatId                   │
│    → DB profile + DSN       │            │    → hotel_id                       │
│    → MySQL连接              │            │    → S14_DSN (复用酒店业务库DSN)      │
│    → skills执行             │            │    → 加载数据/Excel/生成报告          │
│    → 飞书回复               │            │    → HTML报告+飞书卡片回复            │
└──────────────┬──────────────┘            └──────────────┬──────────────────────┘
               │                                          │
    ┌──────────┼──────────┐                   ┌───────────┼───────────┐
    ▼          ▼          ▼                   ▼           ▼           ▼
┌────────┐┌────────┐┌────────┐          ┌────────┐┌────────┐┌────────┐
│全局配置 ││全局配置 ││全局配置 │          │全局配置 ││全局配置 ││全局配置 │
│/etc/   ││/etc/   ││/etc/   │          │/etc/   ││/etc/   ││/etc/   │
│hotel-  ││hotel-  ││hotel-  │          │hotel-  ││hotel-  ││hotel-  │
│ota-ai/ ││ota-ai/ ││ota-ai/ │          │ota-ai/ ││ota-ai/ ││ota-ai/ │
│(共用)  ││(共用)  ││(共用)  │          │(共用)  ││(共用)  ││(共用)  │
└───┬────┘└───┬────┘└───┬────┘          └───┬────┘└───┬────┘└───┬────┘
    │         │         │                   │         │         │
    ▼         ▼         ▼                   ▼         ▼         ▼
┌────────┐┌────────┐┌────────┐          ┌────────┐┌────────┐┌────────┐
│MySQL:  ││MySQL:  ││MySQL:  │          │MySQL:  ││MySQL:  ││MySQL:  │
│hotel_  ││hotel_  ││hotel_  │          │hotel_  ││hotel_  ││hotel_  │
│puyue   ││hotel_a ││hotel_b │          │puyue   ││hotel_a ││hotel_b │
└────────┘└────────┘└────────┘          └────────┘└────────┘└────────┘
   (S14复用同一个MySQL业务库，只读诊断)
```

### 飞书群与机器人对应关系

```
璞悦酒店管理群          酒店A管理群           酒店B管理群
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ 🏨 璞悦收益助手│    │ 🏨 酒店A收益助手│   │ 🏨 酒店B收益助手│
│ 📊 璞悦S14诊断│    │ 📊 酒店AS14   │    │ 📊 酒店B S14  │
│              │    │              │    │              │
│ (两个机器人,  │    │ (两个机器人,  │    │ (两个机器人,  │
│  互不干扰)    │    │  互不干扰)    │    │  互不干扰)    │
└──────────────┘    └──────────────┘    └──────────────┘
```

**铁律：一个飞书群里有且只有同酒店的两个机器人（主助手+S14），绝不能加入其他酒店的任何机器人。**

### 核心设计原则

1. **一个 OpenClaw 进程，两个 Agent，两套代码（主+S14），全部共享不复制**
2. **每个酒店两个飞书机器人应用**（独立 appId/appSecret）：
   - 主收益助手：处理调价、运营快照、促销、评论、审批等
   - S14诊断助手：处理Excel上传诊断、数据库拉取营销诊断报告
3. **一个全局 SQLite auth DB**（现有那个），通过 `hotel_id` + `bot_type` 字段区分
4. **每个酒店独立的 MySQL 业务库**，S14诊断复用同一个库（只读）
5. **消息路由与数据范围分离**：
   - `accountId` 仅用于 OpenClaw `bindings` 把消息路由到对应 agent（以及标记用哪个机器人回复），**不是**酒店数据范围的权威依据
   - 酒店数据范围必须通过可信链路解析：`可信 chat_id → chat_bindings/group_chat_bindings → hotel_id`，发言人身份经 `auth_principals + hotel_memberships` 校验
   - 用户名下的权限也按该 `hotel_id` 判定；未绑定群或未解析到唯一酒店时必须拒绝业务请求
6. **零数据交叉**：A酒店的消息不可能读到B酒店的数据（写路径同样按当前酒店唯一 DSN 路由，缺则 fail closed）
7. **S14卡片回调多租户**：一个HTTP回调服务支持多个飞书应用的卡片按钮事件

---

## 三、具体改造清单

### 改造1：飞书认证插件 —— 放开账号数量限制 + 传递 accountId（主收益助手）

**文件**：`ops/openclaw-plugins/hotel-ota-feishu-auth/index.mjs`

**注意**：此插件只拦截主收益助手的账号（*-chief），不拦截S14账号。S14账号由s14-operation-diagnosis agent自行处理。

```js
// === 改前 ===
function targetAccounts() {
  const configured = (process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS || "")
    .split(",").map(v => v.trim()).filter(Boolean);
  if (configured.length !== 2) {
    throw new Error("...must list exactly two...");
  }
  return new Set(configured);
}

// === 改后 ===
function targetAccounts() {
  const configured = (process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS || "")
    .split(",").map(v => v.trim()).filter(Boolean);
  if (configured.length < 1) {
    throw new Error("...must list at least one...");
  }
  return new Set(configured);
}
```

在 `routeRuntime()` 中新增传递 `--account-id`：

```js
async function routeRuntime(identity) {
  const args = [
    runtimeEntry(), "--db", databasePath(), "feishu-route",
    "--production-feishu",
    "--message", identity.message || "",
    "--chat-id", identity.chatId,
    "--auth-config", authConfigPath(),
    "--account-id", identity.accountId,   // ← 新增
    "--render",
  ];
  // ...
}
```

**改动量**：~10行

---

### 改造2：DB profile 支持 hotel_id 映射（主收益助手）

**文件**：`runtime/adapters/database.py` — `_profile()` 函数

```python
def _profile(config, profile_name=None, hotel_id=None):
    if not config:
        return None
    profiles = config.get("profiles") or {}
    # === 新增 ===
    if not profile_name and hotel_id:
        hotel_map = config.get("hotel_profile_map") or {}
        profile_name = hotel_map.get(hotel_id)
    # === 原有逻辑不变 ===
    selected = profile_name or os.environ.get("HOTEL_OTA_DB_PROFILE") or config.get("default_profile")
    # ... inherits 合并逻辑保持不变 ...
```

在 `runtime/cli.py` → `feishu_route()` 和 `runtime/feishu_command_router.py` 调用链中传递 account_id → 解析 hotel_id → 传给 _profile()。

**文件**：`/etc/hotel-ota-ai/database-source.json` — 新增 `hotel_profile_map`：

```json
{
  "version": 3,
  "default_profile": "puyue_mysql_prod",
  "hotel_profile_map": {
    "puyue": "puyue_mysql_prod"
  },
  "profiles": {
    "puyue_mysql_prod": { ... 保持不变 ... },
    "hotela_mysql_prod": {
      "inherits": "puyue_mysql_prod",
      "db_kind": "mysql",
      "dsn_env": "HOTEL_OTA_DB_DSN_HOTELA",
      "mapping_version": "hotela_27_tables_v1",
      "source_capability": "write_live_pending",
      "hotel_ids": {
        "hotela": { "hotel_name": "酒店A PMS名称", "display_name": "酒店A", "aliases": [] }
      }
    }
  }
}
```

**改动量**：~20行Python + JSON配置

---

### 改造3：多酒店 DSN 环境变量

**文件**：`/etc/hotel-ota-ai/hotel-ota.env`

```bash
# 主业务库 DSN（按酒店命名）
HOTEL_OTA_DB_DSN_PUYUE=mysql+pymysql://user:pass@127.0.0.1:3306/hotel_puyue?charset=utf8mb4
HOTEL_OTA_DB_DSN_HOTELA=mysql+pymysql://user:pass@127.0.0.1:3306/hotel_a?charset=utf8mb4
HOTEL_OTA_DB_DSN_HOTELB=mysql+pymysql://user:pass@127.0.0.1:3306/hotel_b?charset=utf8mb4

# 保持旧的默认值向后兼容
HOTEL_OTA_DB_DSN=mysql+pymysql://user:pass@127.0.0.1:3306/hotel_puyue?charset=utf8mb4

# S14 DSN（S14复用业务库，此处也配置，供s14脚本独立使用）
S14_DB_DSN_PUYUE=mysql+pymysql://user:pass@127.0.0.1:3306/hotel_puyue?charset=utf8mb4
S14_DB_DSN_HOTELA=mysql+pymysql://user:pass@127.0.0.1:3306/hotel_a?charset=utf8mb4
S14_DB_DSN=mysql+pymysql://user:pass@127.0.0.1:3306/hotel_puyue?charset=utf8mb4
```

同时为每个酒店配置调价任务DSN和评论任务DSN环境变量：
```bash
# 调价任务DSN（按酒店）
HOTEL_OTA_PRICE_TASK_DB_DSN_PUYUE=mysql+pymysql://...@127.0.0.1:3306/hotel_puyue?...
HOTEL_OTA_PRICE_TASK_DB_DSN_HOTELA=mysql+pymysql://...@127.0.0.1:3306/hotel_a?...
# 评论任务DSN（按酒店）
HOTEL_OTA_REVIEW_TASK_DSN_PUYUE=mysql+pymysql://...@127.0.0.1:3306/hotel_puyue?...
HOTEL_OTA_REVIEW_TASK_DSN_HOTELA=mysql+pymysql://...@127.0.0.1:3306/hotel_a?...
```

在主agent的 `_dsn_from_args()` 中支持按 dsn_env 名从环境变量读取。
在S14的 `_resolve_dsn()` 和 `_config()` 中支持按 hotel_id 选择 DSN（详见改造11）。

**改动量**：~10行Python + 环境变量配置

---

### 改造3b：统一 _profile() 函数 —— 消除3处重复代码

**问题**：`database.py`、`nearby_events.py`、`hourly_history.py` 三个文件各自独立实现了 `_profile()`、`_dsn_from_profile()`、`_parse_mysql_dsn()`、`_connect_mysql()` 函数，代码重复且逻辑不一致（database.py支持inherits合并，另外两个不支持）。

**方案**：将 `nearby_events.py` 和 `hourly_history.py` 中的重复函数改为从 `database.py` 导入。

```python
# === nearby_events.py 和 hourly_history.py 改前 ===
def _profile(config, profile_name=None):
    selected = profile_name or os.environ.get("HOTEL_OTA_DB_PROFILE") or config.get("default_profile")
    # ...独立实现...

# === 改后 ===
from runtime.adapters.database import _profile, _dsn_from_profile, _parse_mysql_dsn, _connect_mysql
# 删除本文件中的重复定义
```

同时修改 `_profile()` 函数签名增加 `hotel_id` 参数（见改造2），nearby_events和hourly_history的调用处传入hotel_id。

**改动量**：~20行Python（删除重复代码+修改import）

---

### 改造3c：统一DSN解析工具函数 —— S8~S13全部改用

**问题**：S8~S13共6个技能模块各自实现了独立的MySQL连接类和 `from_env()` 方法，全部硬编码回退到 `HOTEL_OTA_DB_DSN_PUYUE`，且调用处都是无参调用 `from_env()`，完全不感知hotel_id。这是**最危险的问题**——S11促销执行和S13评论回复是写入操作，连错库会篡改其他酒店数据。

**方案**：在 `runtime/adapters/database.py`（或新建 `runtime/hotel_dsn.py`）中提供统一的按酒店解析DSN的工具函数，所有S8~S13模块的 `from_env()` 改为接受 `hotel_id` 参数，通过统一函数解析DSN。

**新增统一工具函数**：

```python
# runtime/adapters/database.py 新增

def resolve_hotel_dsn(hotel_id: str | None, purpose: str = "main", explicit_dsn: str | None = None) -> str:
    """统一的按酒店ID解析DSN的工具函数。

    Args:
        hotel_id: 酒店ID，如 "puyue", "hotela"
        purpose: DSN用途，决定环境变量名前缀
            - "main": 主业务库 → HOTEL_OTA_DB_DSN_{HOTEL}
            - "price_task": 调价任务 → HOTEL_OTA_PRICE_TASK_DB_DSN_{HOTEL}
            - "review_task": 评论任务 → HOTEL_OTA_REVIEW_TASK_DSN_{HOTEL}
            - "promotion_control": 促销控制 → HOTEL_OTA_PROMOTION_CONTROL_DSN_{HOTEL}
            - "s8"/"s9"/"s10"/"s12"/"s13": 各技能独立DSN → HOTEL_OTA_S{N}_SOURCE_DSN_{HOTEL}
        explicit_dsn: 显式传入的DSN（最高优先级）

    Returns:
        解析到的DSN字符串

    Raises:
        各模块自定义的DataGap异常（由调用方捕获）
    """
    if explicit_dsn:
        return explicit_dsn

    if hotel_id:
        # 优先按酒店+用途查找环境变量
        suffix = hotel_id.upper().replace("-", "_")
        purpose_env_map = {
            "main": f"HOTEL_OTA_DB_DSN_{suffix}",
            "price_task": f"HOTEL_OTA_PRICE_TASK_DB_DSN_{suffix}",
            "review_task": f"HOTEL_OTA_REVIEW_TASK_DSN_{suffix}",
            "promotion_control": f"HOTEL_OTA_PROMOTION_CONTROL_DSN_{suffix}",
            "s8": f"HOTEL_OTA_S8_SOURCE_DSN_{suffix}",
            "s9": f"HOTEL_OTA_S9_SOURCE_DSN_{suffix}",
            "s10": f"HOTEL_OTA_S10_SOURCE_DSN_{suffix}",
            "s12": f"HOTEL_OTA_S12_SOURCE_DSN_{suffix}",
            "s13": f"HOTEL_OTA_S13_SOURCE_DSN_{suffix}",
        }
        env_name = purpose_env_map.get(purpose, f"HOTEL_OTA_DB_DSN_{suffix}")
        dsn = os.environ.get(env_name)
        if dsn:
            return dsn

        # 回退：该用途的通用环境变量
        generic_env_map = {
            "main": "HOTEL_OTA_DB_DSN",
            "price_task": "HOTEL_OTA_PRICE_TASK_DB_DSN",
            "review_task": "HOTEL_OTA_REVIEW_TASK_DSN",
            "promotion_control": "HOTEL_OTA_PROMOTION_CONTROL_DSN",
        }
        if purpose in generic_env_map:
            dsn = os.environ.get(generic_env_map[purpose])
            if dsn:
                return dsn

    # 最终回退（向后兼容，仅当hotel_id=puyue或None时使用）
    if not hotel_id or hotel_id == "puyue":
        return os.environ.get("HOTEL_OTA_DB_DSN_PUYUE") or ""

    # 非puyue酒店找不到DSN时抛异常（安全：绝不静默回退到璞悦）
    raise RuntimeError(f"DSN not configured for hotel={hotel_id}, purpose={purpose}")
```

**逐个改造S8~S13模块的 `from_env()`**（以S8为例，其余模块模式相同）：

```python
# s08_promotion_display_source.py 改前
@classmethod
def from_env(cls, explicit_dsn=None):
    dsn = explicit_dsn or os.environ.get("HOTEL_OTA_S8_SOURCE_DSN") or os.environ.get("HOTEL_OTA_DB_DSN_PUYUE")
    if not dsn:
        raise S8PromotionDisplayDataGap("s8_display_source_dsn_not_configured")
    return cls(dsn)

# 改后
@classmethod
def from_env(cls, explicit_dsn=None, hotel_id=None):
    from runtime.adapters.database import resolve_hotel_dsn
    try:
        dsn = explicit_dsn or resolve_hotel_dsn(hotel_id, purpose="s8")
    except RuntimeError as exc:
        raise S8PromotionDisplayDataGap("s8_display_source_dsn_not_configured") from exc
    if not dsn:
        raise S8PromotionDisplayDataGap("s8_display_source_dsn_not_configured")
    return cls(dsn)
```

需要改造的模块清单（全部同样模式）：

| 文件 | 类/函数 | purpose | 写入风险 |
|------|---------|---------|---------|
| s08_promotion_display_source.py | S8PromotionDisplayMySQLSource.from_env() | "s8" | 只读 |
| s09_traffic_conversion_real.py | S09MySQLSource.from_env() | "s9" | 只读 |
| s10_promotion_source.py | S10MySQLSource.from_env() | "s10" | 只读 |
| s11_promotion_execution_patch.py | _promotion_control_dsn() | "promotion_control" | **🔴写入** |
| s12_reputation_real.py | S12MySQLSource.from_env() | "s12" | 只读 |
| s13/source.py | MySQLReviewSourceRepository.from_env() | "s13" | 只读 |
| s13/task_outbox.py | MySQLReviewTaskOutbox.from_env() | "review_task" | **🔴写入** |
| adapters/zhiting_price_task_outbox.py | 直接读env | "price_task" | **🔴写入** |
| adapters/s6_fast_outbox_guard.py | 直接读env | "price_task" | **🔴写入** |
| decisions/pricing.py | 直接读env | "price_task" | **🔴写入** |

**调用处修改**：所有调用 `from_env()` 的地方需要传入当前请求的 `hotel_id`。主要在：
- `s01_s17_exact_route_patch.py`：S9/S12/S10的from_env()调用
- `s11_promotion_execution_patch.py`：S8查询和促销控制DSN
- `feishu_command_router.py`：各种技能调用链
- CLI入口和cron任务

**改动量**：~120行Python（工具函数30行 + 9个模块改造约10行×9=90行）

---

### 改造4：SQLite —— 复用现有认证表，无需新增账号表

**决策：保持使用全局单个SQLite**（`/var/lib/hotel-ota-ai/hotel_ops.sqlite`），并**复用现有表结构，不新增 `feishu_accounts` 表**。

> ⚠️ **勘误（相对初版）**：初版以为可以新建 `feishu_accounts` 表存"账号→酒店/机器人类型"。经核对 `runtime/storage.py`，**该表不存在**，且运行时也没有从 accountId 查 hotel_id 的路径。实际认证依赖的是下面这些**已存在的表**：

| 表 | 字段 | 在多酒店中的作用 |
|----|------|-----------------|
| `chat_bindings` / `group_chat_bindings` | `chat_id → hotel_id` | 可信群绑定，是解析酒店数据范围的**唯一权威来源** |
| `auth_principals` | 身份、`is_global_admin` | 发言人身份解析、是否全局管理员 |
| `hotel_memberships` | `principal_id + hotel_id → role` | 用户在某酒店的权限角色 |
| `control_plane` 的 BIND/ROLE 请求表 | 审批流程数据 | 群绑定、角色变更需经审批落库 |

**结论**：
- 多酒店**不需要**任何新的账号表或 SQL 迁移
- 酒店数据范围一律以 `chat_bindings.hotel_id` 为准（经 BIND 流程写入），`accountId` 不入库
- 因此初版中的改造 6、新增酒店流程里的"`INSERT INTO feishu_accounts`"全部删除，改为基于 chat_bindings 的解析与 BIND/ROLE 流程

**改动量**：0 行 SQL（仅代码里确保按 chat_id 查询 chat_bindings 解析 hotel_id，见改造 6）

---

### 改造5：路径解析 —— 日志/报告/经验按酒店分目录

**文件**：`runtime/common.py`（主agent）

```python
def hotel_scoped_dir(base_dir, hotel_id=None, subdir=None):
    if not hotel_id:
        return base_dir
    parts = [base_dir, hotel_id]
    if subdir:
        parts.append(subdir)
    return str(Path(*parts))
```

S14报告目录已经在 `_report_dir()` 中按 hotel_id 分段（`root/hotel/platform/period/run_id`），只需确保 `output_root` 配置正确即可，S14端无需额外改路径逻辑。但S14的 `STATE_DIR`（`/tmp/s14_state/`）保持全局，因为文件名已包含chat_id天然隔离。

**改动量**：~20行Python

---

### 改造6：主agent消息入口 —— 从可信 chat_id 解析 hotel_id

**文件**：`runtime/cli.py` 新增 `--chat-id` / `--account-id`（accountId 仅用于校验插件侧路由的来源）
**文件**：`runtime/feishu_command_router.py` 在路由前通过 `chat_id` 查 `chat_bindings` 得到 hotel_id

```python
# CLI新增
p.add_argument("--account-id", default=None, help="Feishu account ID (bindings来源,仅用于校验)")
p.add_argument("--chat-id", required=True, help="Feishu chat ID (酒店数据范围解析依据)")

# 路由入口: chat_id → chat_bindings → hotel_id（权威来源）
hotel_id = lookup_chat_binding(db_path, chat_id)   # 查 chat_bindings 表
if not hotel_id:
    raise_blocked("unbound_chat")   # 未绑定群一律拒绝业务，不静默回退
```

> **关键**：`accountId` 只会来自 openclaw 插件侧，用于告诉运行时"这条消息是从哪个机器人账号进来的"（便于校验插件确实拦截了对应 *-chief 账号），**不参与酒店解析**。酒店数据范围由 `chat_bindings(chat_id)→hotel_id` 决定，随后把 `hotel_id` 传入 `build_auth_context` 与 DB profile 解析。

**改动量**：~20行Python

---

### 改造7：OpenClaw 配置 —— 每个酒店新增两个飞书账号和bindings

**文件**：`/root/.openclaw/openclaw.json`

每新增一个酒店，在 `channels.feishu.accounts` 中添加两个账号，在 `bindings` 中添加两条路由：

```json
{
  "channels": {
    "feishu": {
      "accounts": {
        "default-hotel-ota-ai": { ... 现有璞悦主助手，保持不变 ... },
        "hotel-ota-ai-test": { ... 现有测试，保持不变 ... },
        "s14-ext": { ... 现有璞悦S14，保持不变 ... },
        "s14-ext-test": { ... 现有S14测试，保持不变 ... },

        "hotela-chief": {
          "enabled": true,
          "groupPolicy": "allowlist",
          "appId": "cli_hotela_chief_xxx",
          "appSecret": "xxx",
          "requireMention": false,
          "dmPolicy": "open",
          "groupAllowFrom": ["*"],
          "allowFrom": ["*"]
        },
        "hotela-s14": {
          "enabled": true,
          "groupPolicy": "allowlist",
          "appId": "cli_hotela_s14_xxx",
          "appSecret": "xxx",
          "requireMention": false,
          "dmPolicy": "open",
          "groupAllowFrom": ["*"],
          "allowFrom": ["*"]
        }
      }
    }
  },
  "bindings": [
    { "type": "route", "agentId": "hotel-ota-chief",
      "match": { "channel": "feishu", "accountId": "default-hotel-ota-ai" } },
    { "type": "route", "agentId": "hotel-ota-chief",
      "match": { "channel": "feishu", "accountId": "hotel-ota-ai-test" } },
    { "type": "route", "agentId": "s14-operation-diagnosis",
      "match": { "channel": "feishu", "accountId": "s14-ext" } },
    { "type": "route", "agentId": "s14-operation-diagnosis",
      "match": { "channel": "feishu", "accountId": "s14-ext-test" } },
    { "type": "route", "agentId": "hotel-ota-chief",
      "match": { "channel": "feishu", "accountId": "hotela-chief" } },
    { "type": "route", "agentId": "s14-operation-diagnosis",
      "match": { "channel": "feishu", "accountId": "hotela-s14" } }
  ]
}
```

更新认证插件环境变量（只列主助手账号，S14不走认证插件）：
```bash
HOTEL_OTA_FEISHU_AUTH_ACCOUNTS=default-hotel-ota-ai,hotel-ota-ai-test,hotela-chief
```

**改动量**：每新增酒店约25行JSON配置

---

### 改造8：配置文件新增酒店

**market-source.json** 和 **s14-source.json** 已经按 hotel_id 索引，直接追加即可（无需改代码）。s14-source.json 中S14的 profile 指向对应的数据库 profile。

---

### 改造9：S14 入口脚本支持多酒店（核心改造）

**文件**：`/opt/openclaw/workspaces/ota-marketing-diagnosis/scripts/s14_feishu_entry.py`

**9a. CLI新增 `--account-id` 与 `--chat-id` 参数：**

```python
parser.add_argument("--account-id", default=os.environ.get("FEISHU_ACCOUNT_ID", ""))
parser.add_argument("--chat-id", default=os.environ.get("FEISHU_CHAT_ID", ""))
```

**9b. 新增 chat_id → hotel_id 解析函数（群绑定优先）：**

S14是独立进程，原则上以接入方传入的 `--chat-id` 为准；若 S14 具备读主agent SQLite 的能力，则与主agent同源（查 `chat_bindings`）。否则使用 S14 侧维护的群绑定映射 `s14-account-map.json`（由部署者按 BIND 结果同步），**不能仅凭 accountId 定位酒店**：

```python
def _resolve_hotel_id(chat_id, account_id):
    """酒店定位优先走可信群绑定，accountId不作为数据范围依据"""
    # 方式1: 若S14能读主agent SQLite，按chat_id查 chat_bindings（与主agent同源）
    if sqlite_available():
        hotel = lookup_chat_binding(sqlite_path, chat_id)   # chat_bindings 表
        if hotel:
            return hotel
    # 方式2: 从 S14 侧同步的群绑定映射按 chat_id 查（需与主agent BIND结果一致）
    mapping = _load_s14_account_map()  # /etc/hotel-ota-ai/s14-account-map.json
    if chat_id and chat_id in mapping:
        return mapping[chat_id]["hotel_id"]
    # 方式3: 唯一允许的向后兼容——无任何绑定信息时默认"puyue"（仅璞悦单酒店）
    if not chat_id or is_legacy_puyue_single():
        return "puyue"
    raise_blocked("unbound_chat")   # 多酒店场景下未绑定群拒绝
```

**9c. 改造 `_config()` 根据 hotel_id 选择 DSN：**

```python
def _config(hotel_id="puyue"):
    cfg = {}
    # 根据hotel_id选择DSN环境变量
    dsn_env = f"S14_DB_DSN_{hotel_id.upper()}"
    if os.environ.get(dsn_env):
        cfg["db_dsn"] = os.environ[dsn_env]
        cfg["db_dsn_env"] = dsn_env
    elif os.environ.get("S14_DB_DSN"):
        cfg["db_dsn"] = os.environ["S14_DB_DSN"]
        cfg["db_dsn_env"] = "S14_DB_DSN"

    # 报告目录按酒店隔离（S14 _report_dir已含hotel分段，output_root用公共目录即可）
    if os.environ.get("S14_REPORT_OUTPUT_DIR"):
        cfg["report_output_dir"] = os.environ["S14_REPORT_OUTPUT_DIR"]
    if os.environ.get("S14_PUBLIC_BASE_URL"):
        cfg["public_base_url"] = os.environ["S14_PUBLIC_BASE_URL"]
    return cfg
```

**9d. 改造 `_hotel()` 使用动态配置而非硬编码别名：**

```python
def _hotel(text, hotel_id="puyue"):
    """S14场景下，hotel_id已从accountId确定，不需要从文本猜测"""
    # 从 s14-source.json 加载酒店显示名
    hotel_name = _load_hotel_display_name(hotel_id)
    return hotel_id, hotel_name
```

**9e. 改造 `_request_context()` 和 `_run_database()` 传递 hotel_id：**

```python
def _request_context(text, *, hotel_id="puyue", sender_id=None):
    # ...
    return {
        "hotel_id": hotel_id,
        "hotel_name": _load_hotel_display_name(hotel_id),
        # ...其余字段
    }
```

**改动量**：~60行Python

---

### 改造10：S14 Skill 类支持动态 hotel_id 和 DSN

**文件**：`/opt/openclaw/workspaces/ota-marketing-diagnosis/skills/s14-operation-diagnosis/runtime/__init__.py`

**10a. `_resolve_dsn()` 支持按 hotel_id 选择：**

```python
def _resolve_dsn(self, hotel_id=None):
    load_local_s14_env()
    # 优先使用config中的db_dsn
    if self.config.get("db_dsn"):
        return self.config["db_dsn"]
    # 按hotel_id查找环境变量
    if hotel_id:
        env_name = f"S14_DB_DSN_{hotel_id.upper()}"
        dsn = os.environ.get(env_name)
        if dsn:
            return dsn
    # 默认
    env_name = self.config.get("db_dsn_env") or "S14_DB_DSN"
    return os.environ.get(env_name) or os.environ.get("S14_DB_DSN")
```

**10b. `execute()` 中 database 模式使用传入的 hotel_id：**

```python
elif mode == "database":
    dsn = self._resolve_dsn(prepared.get("hotel_id"))
    # ...其余不变
```

**10c. `_prepare_inputs()` 默认 hotel_id 不再硬编码 "puyue"，而是从config获取：**

```python
"hotel_id": inputs.get("hotel_id") or self.config.get("default_hotel_id") or "puyue",
```

**改动量**：~15行Python

---

### 改造11：S14 卡片回调服务支持多租户（多飞书应用）

**文件**：`/opt/openclaw/workspaces/ota-marketing-diagnosis/scripts/s14_feishu_card_callback.py`

这是S14多酒店的**最复杂改造点**。当前回调服务只支持单个飞书应用（一组appId/appSecret/verificationToken），多酒店后需要支持多个。

**方案：单HTTP服务 + 多飞书Client路由**

核心思路：启动时加载所有酒店的S14飞书应用配置，按app_id路由到对应的Client发送消息。回调URL可以共用一个（飞书在回调payload中带app_id），也可以每个酒店用不同路径。

```python
import dataclasses

@dataclasses.dataclass
class S14BotConfig:
    hotel_id: str
    app_id: str
    app_secret: str
    verification_token: str
    encrypt_key: str = ""

def _load_s14_bot_configs() -> dict[str, S14BotConfig]:
    """从环境变量或配置文件加载所有酒店S14机器人配置"""
    configs = {}
    # 方式1: 从 /etc/hotel-ota-ai/s14-account-map.json 的 bots 段加载
    map_path = os.environ.get("S14_ACCOUNT_MAP", "/etc/hotel-ota-ai/s14-account-map.json")
    if Path(map_path).exists():
        data = json.loads(Path(map_path).read_text(encoding="utf-8"))
        for account_id, info in (data.get("bots") or {}).items():
            hotel_id = info["hotel_id"]
            # 从环境变量读取对应凭证（appId/appSecret在openclaw.json中，但回调服务也需要）
            prefix = f"S14_BOT_{hotel_id.upper()}"
            configs[info["app_id"]] = S14BotConfig(
                hotel_id=hotel_id,
                app_id=info["app_id"],
                app_secret=os.environ.get(f"{prefix}_APP_SECRET", ""),
                verification_token=os.environ.get(f"{prefix}_VERIFICATION_TOKEN", ""),
                encrypt_key=os.environ.get(f"{prefix}_ENCRYPT_KEY", ""),
            )
    return configs
```

> 说明：`_load_s14_bot_configs()` 只为**卡片回调**按 app_id 路由到对应飞书Client；回调无法拿到用户 message 的 chat 绑定，故此处以 app_id → hotel_id/凭证 对应。消息入口（聊天）的酒店定位仍走改造9b的 `groups[chat_id]` 群绑定路径。

**回调服务改造为多app模式：**

```python
def create_app():
    bot_configs = _load_s14_bot_configs()
    # 为每个bot创建独立的飞书Client和handler
    clients = {}
    handlers = {}
    for app_id, cfg in bot_configs.items():
        client = lark.Client.builder().app_id(cfg.app_id).app_secret(cfg.app_secret).build()
        clients[app_id] = client
        handlers[app_id] = (
            lark.EventDispatcherHandler.builder(cfg.encrypt_key, cfg.verification_token)
            .register_p2_card_action_trigger(on_card_action_factory(client, cfg))
            .build()
        )

    @app.post(callback_path)
    def card_callback():
        # 从请求中识别是哪个app的回调，路由到对应handler
        # 飞书回调header或body中包含app_id
        # 注意：Flask需要先读取body判断app_id
        raw_data = request.get_data(as_text=True)
        payload = json.loads(raw_data)
        app_id = payload.get("header", {}).get("app_id", "")
        handler = handlers.get(app_id)
        if not handler:
            return jsonify({"code": 404, "msg": f"unknown app_id: {app_id}"}), 404
        return handler.do(parse_req(request))
    # ...
```

**环境变量配置（每酒店S14机器人一组）：**

```bash
# 璞悦S14
S14_BOT_PUYUE_APP_SECRET=xxx
S14_BOT_PUYUE_VERIFICATION_TOKEN=xxx
# 酒店A S14
S14_BOT_HOTELA_APP_SECRET=xxx
S14_BOT_HOTELA_VERIFICATION_TOKEN=xxx
```

**飞书回调URL**：每个S14应用在飞书后台配置同一个回调地址：
```
https://YOUR_DOMAIN/s14/feishu/card-callback
```
服务端根据回调payload中的app_id自动路由到对应凭证处理。

**注意**：卡片回调的 `send_message` 需要用触发卡片的那个bot（同一个app）来发送回复，否则消息会发错bot或发不出去。上述多client方案已解决此问题。

**改动量**：~80行Python

---

### 改造12：S14 配置文件 —— s14-account-map.json

在 `/etc/hotel-ota-ai/` 下新增 S14 群绑定/应用的映射配置文件。

**文件**：`/etc/hotel-ota-ai/s14-account-map.json`

> ⚠️ **原则（与主agent一致）**：酒店数据范围以**群（chat_id）**为准，不以 accountId 为准。因此本文件同时维护两类信息：
> - `groups[chat_id]`：群 → hotel_id（由部署者按主agent BIND 结果同步）
> - `bots[account_id]`：S14机器人账号 → 归属酒店 + 卡片回调凭证

```json
{
  "groups": {
    "oc_puyue_s14_group": { "hotel_id": "puyue" },
    "oc_hotela_s14_group": { "hotel_id": "hotela" }
  },
  "bots": {
    "s14-ext": { "hotel_id": "puyue", "app_id": "cli_puyue_s14_xxx", "display_name": "璞悦S14诊断助手" },
    "hotela-s14": { "hotel_id": "hotela", "app_id": "cli_hotela_s14_xxx", "display_name": "酒店A S14诊断助手" }
  }
}
```

此文件供S14入口脚本（按 `groups[chat_id].hotel_id` 解析数据范围）和卡片回调服务（按 `bots[account_id].app_id` 路由到对应飞书Client）共同使用。

**改动量**：新增配置文件

---

## 四、消息路由链路

### 4.1 主收益助手消息流程

```
1. 用户在酒店A的群发 "调价建议" → @酒店A收益助手
   │
   ▼
2. 飞书WS推送 → OpenClaw (accountId="hotela-chief", chatId="oc_xxx")
   │
   ▼
3. bindings匹配 → agentId="hotel-ota-chief"
   │
   ▼
4. hotel-ota-feishu-auth 插件拦截（accountId在认证列表中）:
   - 调用Python feishu-route --chat-id oc_xxx --account-id hotela-chief
   │
   ▼
5. Python: 由 chat_bindings 查 oc_xxx → hotel_id="hotela" (accountId仅校验来源)
   → 群未绑定 → 拒绝业务 (unbound_chat)
   → build_auth_context 验证用户在该hotel的权限
   → hotel_profile_map["hotela"] → "hotela_mysql_prod"
   → DSN = HOTEL_OTA_DB_DSN_HOTELA → 连 hotel_a MySQL
   → log_dir = /var/log/hotel-ota-ai/hotela/
   │
   ▼
6. 执行S05 skill → 读取hotel_a数据 → 生成回复
   │
   ▼
7. openclaw message send --account hotela-chief → 飞书 → 酒店A群
```

### 4.2 S14诊断助手消息流程

```
1. 用户在酒店A的群发 "S14诊断" → @酒店A S14诊断助手
   │
   ▼
2. 飞书WS推送 → OpenClaw (accountId="hotela-s14", chatId="oc_yyy")
   │
   ▼
3. bindings匹配 → agentId="s14-operation-diagnosis"
   （S14账号不在HOTEL_OTA_FEISHU_AUTH_ACCOUNTS中，不走认证插件）
   │
   ▼
4. s14-operation-diagnosis agent 处理消息:
   - OpenClaw将消息传入S14 skill
   - S14 skill调用 s14_feishu_entry.py --account-id hotela-s14 --chat-id oc_yyy
   │
   ▼
5. s14_feishu_entry.py 解析:
   - 按 groups[chat_id].hotel_id 解析 → hotel_id="hotela"（群绑定优先，accountId仅对应确认bot凭证）
   - 确认该bot归属hotela（bots[hotela-s14].hotel_id）
   - _config(hotel_id="hotela") → DSN = S14_DB_DSN_HOTELA
   → 连 hotel_a MySQL（只读）
   → report_dir = S14_REPORT_OUTPUT_DIR/hotela/multi/...
   │
   ▼
6. 执行S14诊断（数据库模式/Excel模式）
   → 生成HTML报告 → 飞书卡片+文本回复
   │
   ▼
7. OpenClaw 通过hotela-s14账号发送回复 → 酒店A群
```

### 4.3 S14卡片按钮回调流程

```
1. 用户在酒店A群点击S14卡片上的"数据库"按钮
   │
   ▼
2. 飞书发送card.action.trigger HTTPS回调到服务器
   POST /s14/feishu/card-callback
   payload中含: header.app_id = "cli_hotela_s14_xxx", chat_id = oc_yyy
   │
   ▼
3. 多租户回调服务:
   - 根据app_id查找到对应的S14BotConfig(hotel_id="hotela")
   - 使用该bot的verification_token验签
   - 使用该bot的飞书Client发送后续消息
   │
   ▼
4. 调用handle_card_source_choice(source="database", chat_id=oc_yyy, ...)
   → s14_feishu_entry.py中加载hotel_id="hotela"上下文
   → 执行数据库诊断
   │
   ▼
5. 通过hotela-s14的飞书Client将报告卡片发送到oc_yyy群
```

---

## 五、新增酒店操作流程（完整步骤）

每新增一个酒店，需要创建**两个**飞书应用并完成以下配置：

### 5.1 飞书开放平台（创建2个应用）

**应用1：主收益助手**
- 创建企业自建应用
- 添加机器人能力
- 申请权限：`im:message`、`im:message:send_as_bot`、`im:chat` 等
- 事件订阅：WS模式接收 `im.message.receive_v1`（不需要HTTP回调）
- 发布版本 → 管理员审核

**应用2：S14诊断助手**
- 创建企业自建应用
- 添加机器人能力
- 申请权限：`im:message`、`im:message:send_as_bot`、`im:chat`、`im:resource`（上传Excel需要）
- 事件订阅：
  - WS模式接收 `im.message.receive_v1`（接收文本和文件消息）
  - HTTP回调配置：`card.action.trigger` → `https://YOUR_DOMAIN/s14/feishu/card-callback`
- 记录 appId、appSecret、verification_token、encrypt_key
- 发布版本 → 管理员审核

### 5.2 服务器配置

```bash
HOTEL_ID=hotela    # 替换为新酒店ID
HOTEL_NAME="酒店A"  # 替换为酒店名

# === 1. 环境变量 ===
cat >> /etc/hotel-ota-ai/hotel-ota.env <<EOF
HOTEL_OTA_DB_DSN_${HOTEL_ID^^}=mysql+pymysql://openclaw_user:PASS@127.0.0.1:3306/hotel_${HOTEL_ID}?charset=utf8mb4
S14_DB_DSN_${HOTEL_ID^^}=mysql+pymysql://openclaw_user:PASS@127.0.0.1:3306/hotel_${HOTEL_ID}?charset=utf8mb4
S14_BOT_${HOTEL_ID^^}_APP_SECRET=<S14应用的appSecret>
S14_BOT_${HOTEL_ID^^}_VERIFICATION_TOKEN=<S14应用的verification_token>
EOF

# === 2. openclaw.json 添加账号和bindings ===
# 参照改造7，在channels.feishu.accounts添加 ${HOTEL_ID}-chief 和 ${HOTEL_ID}-s14 两个账号
# 在bindings添加两条路由规则
vim /root/.openclaw/openclaw.json

# === 3. 更新认证插件账号列表 ===
# HOTEL_OTA_FEISHU_AUTH_ACCOUNTS 追加 ${HOTEL_ID}-chief（S14账号不加）
sed -i "s/HOTEL_OTA_FEISHU_AUTH_ACCOUNTS=.*/&,${HOTEL_ID}-chief/" /etc/hotel-ota-ai/hotel-ota.env

# === 4. database-source.json 添加profile ===
# 参照改造2，添加 ${HOTEL_ID}_mysql_prod（inherits puyue_mysql_prod）
vim /etc/hotel-ota-ai/database-source.json

# === 5. feishu-role-map.json 添加用户和群绑定 ===
# 添加group_chat_bindings和hotel_memberships
vim /etc/hotel-ota-ai/feishu-role-map.json

# === 6. market-source.json 添加市场配置 ===
vim /etc/hotel-ota-ai/market-source.json

# === 7. s14-source.json 添加S14数据源 ===
vim /etc/hotel-ota-ai/s14-source.json

# === 8. s14-account-map.json 添加S14账号映射 ===
vim /etc/hotel-ota-ai/s14-account-map.json

# === 9. 创建目录 ===
mkdir -p /var/log/hotel-ota-ai/${HOTEL_ID}/
mkdir -p /var/lib/hotel-ota-ai/s14/${HOTEL_ID}/
mkdir -p /var/lib/hotel-ota-ai/s14/reports/${HOTEL_ID}/
mkdir -p /var/lib/hotel-ota-ai/experience/${HOTEL_ID}/
mkdir -p /var/lib/ota-marketing-diagnosis/reports/${HOTEL_ID}/

# === 10. 认证与群绑定（BIND/ROLE 受控流程，禁止手工SQL） ===
# 在璞悦群中由管理员执行：把新酒店的两个群 chat_id 绑定到 ${HOTEL_ID}
#   通过 openclaw BIND 命令完成 chat_bindings 写入（走审批+审计）
#   通过 openclaw ROLE 命令为员工写 auth_principals + hotel_memberships
# 不要直接 INSERT feishu_accounts：该表不存在，且绕过审计
# chat_id 可在新群 @机器人 后从日志中获取

# === 11. 重启服务 ===
openclaw gateway restart
# 如果S14卡片回调服务以systemd运行：
systemctl restart s14-feishu-card-callback
```

### 5.3 飞书端验证

1. 将**两个机器人**都拉入酒店A的飞书群（主助手+S14）
2. 对主助手发"菜单" → 验证回复数据来自酒店A数据库
3. 对S14助手发"S14诊断" → 选择"数据库" → 验证报告数据来自酒店A数据库
4. 验证璞悦群功能正常（无回归）
5. 确认两个群的机器人互不串扰（在A群发消息，璞悦群不会收到任何回复）

---

## 六、改造工作量汇总

### 主收益助手 (hotel-ota-chief)

| # | 改造项 | 文件数 | 代码行数 | 难度 | 风险 |
|---|--------|--------|---------|------|------|
| ① | 插件账号限制放开+传accountId | 1 | ~10行 | 低 | 低 |
| ② | DB profile按hotel_id映射（3个_profile副本统一） | 3 | ~50行 | 中 | 中 |
| ③ | 多DSN环境变量支持 | 2（py）+1（env） | ~10行 | 低 | 低 |
| ③b | _profile()去重（nearby_events/hourly_history导入database.py） | 2 | ~20行 | 低 | 低 |
| ③c | **统一DSN解析resolve_hotel_dsn() + S8~S13全部from_env()改造（含写入路径）** | **10+** | **~120行** | **高** | **🔴高** |
| ④ | 复用现有认证表(chat_bindings)解析hotel_id，不新增表 | 0 | ~10行 | 低 | 低 |
| ⑤ | 路径按酒店分目录 | 2-3 | ~20行 | 中 | 低 |
| ⑥ | CLI新增account-id+chat-id，按chat_bindings解析hotel_id | 2 | ~20行 | 中 | 低 |
| ⑦ | openclaw.json双账号配置 | 配置 | ~30行/酒店 | 低 | 低 |
| ⑧ | market/s14-source新增酒店 | 配置 | ~20行/酒店 | 低 | 低 |

### S14诊断助手 (s14-operation-diagnosis)

| # | 改造项 | 文件数 | 代码行数 | 难度 | 风险 |
|---|--------|--------|---------|------|------|
| ⑨ | S14入口脚本多酒店DSN/hotel_id | 1 | ~60行 | 中 | 中 |
| ⑩ | S14 Skill类动态DSN解析 | 1 | ~15行 | 低 | 低 |
| ⑪ | S14卡片回调多租户支持 | 1 | ~80行 | 高 | 中 |
| ⑫ | s14-account-map.json配置 | 配置 | ~15行/酒店 | 低 | 低 |

**总计：约435-495行代码改动（主agent约280行 + S14约155行 + 配置约65行/酒店）**

> **⚠️ 与初版方案对比**：初版估算约275-310行，经过代码逐行审查后发现S8~S13技能模块存在大面积硬编码回退璞悦DSN的问题（尤其是S11促销写入、S13评论写入、调价任务写入3条写入路径），需要统一DSN解析工具+逐模块改造，增加约140行代码。这是**数据安全**必须做的改造——否则多酒店上线后，写入操作可能误改其他酒店数据。

---

## 七、向后兼容策略

1. 所有新逻辑通过"有hotel_id走新路径，无hotel_id走旧路径"方式实现
2. `hotel_profile_map` 默认 `"puyue": "puyue_mysql_prod"`
3. 环境变量保留旧的 `HOTEL_OTA_DB_DSN` 和 `S14_DB_DSN` 作为默认回退
4. `resolve_hotel_dsn()` 安全策略：**非puyue酒店找不到对应DSN时直接抛异常，绝不静默回退到璞悦库**（防止写入操作误改璞悦数据）
5. puyue酒店在hotel_id=None或"puyue"时保持原有的PUYUE DSN回退链，确保现有功能零回归
6. **认证用现有表，不新增**：`chat_bindings`/`group_chat_bindings` 已预置璞悦群绑定，`auth_principals` 已预置现有用户；不新增 `feishu_accounts` 表
7. S14 `_hotel()` 无群绑定信息时默认返回"puyue"（仅允许璞悦单酒店向后兼容；多酒店场景必须经群绑定解析）
8. S14卡片回调无多酒店配置时回退到单app模式
9. 不修改任何现有profile和配置，只追加

---

## 八、风险和注意事项

| 风险 | 应对措施 |
|------|---------|
| 一个群加了两个酒店的机器人导致串扰 | **铁律：一个群只能加同酒店的两个机器人。** 上线前检查每个群的机器人列表 |
| 主助手和S14在同一个群会不会重复回复？ | 不会。它们触发词不同：主助手响应"菜单/调价/快照"等，S14响应"S14诊断/运营诊断"等。即使触发词相同，也只有被@的机器人会回复（requireMention=false但OpenClaw按accountId路由） |
| S14卡片回调多租户路由失败 | 回调payload中必须包含app_id；启动时校验所有bot配置完整性；单app回退路径保留 |
| S14卡片回调消息用错bot发送 | 必须用触发回调的那个app_id对应的飞书Client发消息，否则会403或发到错误的群 |
| 飞书应用权限问题（S14需要接收文件） | S14应用额外开通 `im:resource` 权限用于接收Excel文件上传 |
| Excel文件下载需要app鉴权 | S14下载用户上传的Excel时，必须使用接收到消息的那个bot的token |
| cron定时任务写死 --hotel-id puyue | 改为遍历所有激活的酒店 |
| S14回调服务与openclaw-gateway重启顺序 | S14回调服务是独立进程，需确保在openclaw-gateway之后启动，并使用正确的环境变量 |
| 单酒店bug影响全局 | 增加hotel_id维度的错误隔离和try-catch |
| 全局admin跨酒店操作 | global_admin_principal_ids的用户可以操作所有酒店（符合预期） |

---

## 九、实施顺序建议

**Phase 1 — 主收益助手基础设施改造**
1. 改造①：插件放开账号限制+传accountId
2. 改造⑥：CLI新增account-id+chat-id，按 chat_bindings 解析 hotel_id（璞悦群已绑定）
3. 改造④：无需建表，复用现有 chat_bindings/auth_principals（确认璞悦绑定已就位）
4. 改造②：DB profile增加hotel_id映射
5. 改造⑤：路径按酒店分目录
6. 改造③：多DSN环境变量支持
7. 回归验证：璞悦主助手功能正常

**Phase 2 — S14多酒店改造**
8. 改造⑨：S14入口脚本支持chat-id/account-id/hotel_id/动态DSN
9. 改造⑩：S14 Skill类动态DSN
10. 改造⑫：s14-account-map.json配置（groups群绑定 + bots机器人凭证）
11. 改造⑪：S14卡片回调多租户
12. 回归验证：璞悦S14诊断功能正常（数据库+Excel+卡片按钮）

**Phase 3 — 接入第一个新酒店端到端验证**
13. 创建新酒店两个飞书应用（主+S14），配置权限和事件
14. 配置openclaw.json双账号+bindings
15. 配置DSN环境变量+database profile
16. 配置feishu-role-map/market-source/s14-source/s14-account-map
17. 用 BIND 流程绑定新酒店两个群（chat_id→newhotel），ROLE 流程配成员角色
18. 创建目录，重启gateway和S14回调服务
19. 端到端测试：主助手回复、S14诊断、卡片按钮、Excel上传
20. 回归验证：璞悦群（主+S14）功能完全正常

**Phase 4 — 完善和运维工具**
21. 更新cron任务支持多酒店
22. 编写"添加新酒店"一键脚本
23. 添加跨酒店健康检查命令
24. 更新Nginx配置
25. 编写运维手册

---

## 十、不采用的备选方案及原因

| 备选方案 | 不采用原因 |
|---------|-----------|
| 主助手和S14合并为一个机器人 | 用户场景不同：主助手处理日常运营指令，S14处理专业诊断报告，分开更清晰；且S14有独立的卡片回调服务和文件上传需求，合并会增加复杂度 |
| 每酒店一个workspace+软链 | 管理复杂度高，两套workspace都要复制，软链兼容性不确定 |
| 每酒店一个OpenClaw进程 | 资源开销大，进程管理复杂 |
| S14每酒店独立回调端口 | 端口管理复杂，防火墙/Nginx配置成倍增加；单端口多app路由更优雅 |
| S14也走主agent的认证插件 | S14是独立agent，认证插件只拦截主助手账号；S14保持轻量级自行处理路由 |
| 每酒店独立SQLite | 入口时无法认证，全局admin无法跨管理 |
