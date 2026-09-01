# 多酒店配置修改指南（运维人员版）

> **当前生产基线（2026-08-24）**：已接入璞悦与智町，各自使用 chief + S14 两个独立飞书账号。所有新增账号必须使用精确的 `groupAllowFrom` 群列表，禁止 `"*"`；生产 profile 必须命名为 `*_mysql_prod` 并显式声明唯一 `hotel_id`。写入 DSN 一律使用 `_<HOTEL_ID>` 精确变量；缺失能力保持 fail-closed。本文其余旧示例如与本说明冲突，以此说明和 `hotel-onboarding-checklist.md` 为准。


> 本文档说明多酒店上线所需的配置、代码前置条件和验收步骤。每个酒店使用独立数据库；运行时必须按已鉴权的酒店范围选择该酒店的独立连接。
> 面向：运维/部署人员；其中“代码前置条件”必须由开发完成并通过测试后，才能执行后续生产配置。
> 安全要求：本文只使用占位符，不记录真实 App ID、App Secret、Token、DSN、群 ID 或用户身份。

---

## 一、先理解整体结构

### 1.1 现在有几个机器人？

目前系统里有 **2个生产机器人** + **2个测试机器人**，共4个飞书账号：

| 机器人 | 飞书账号ID | 做什么 | 对应飞书应用 |
|--------|-----------|--------|-------------|
| 🏨 酒店数字员工（璞悦） | `default-hotel-ota-ai` | 日常运营：调价、快照、促销、评论等 | 璞悦收益助手 |
| 🏨 酒店数字员工（测试） | `hotel-ota-ai-test` | 测试用，不用于生产 | 测试机器人 |
| 📊 S14诊断机器人（璞悦） | `s14-ext` | S14营销诊断报告、Excel上传分析 | 璞悦S14诊断助手 |
| 📊 S14诊断机器人（测试） | `s14-ext-test` | 测试用，不用于生产 | S14测试机器人 |

**当前部署示例中，一个酒店使用 2 个机器人：1 个数字员工 + 1 个 S14 诊断。** 这是产品与流程选择；多酒店隔离以“可信群绑定/角色 → `hotel_id` → 该酒店独立数据库连接”为准，不能依赖机器人数量。

比如：
- 璞悦酒店群里有：`璞悦收益助手` + `璞悦S14诊断助手`
- 如需独立品牌/报告入口，新酒店A可使用：`酒店A收益助手` + `酒店AS14诊断助手`（两个新飞书应用）

### 1.2 机器人怎么知道该回复哪个酒店？

`accountId` 用于把消息路由到对应的机器人后台；它**不是**酒店数据范围的权威依据。

酒店范围和角色必须按以下链路解析：

```text
可信 chat_id -> SQLite chat_bindings / group_chat_bindings -> hotel_id
可信发言人身份 -> auth_principals + hotel_memberships -> 该 hotel_id 下的角色
hotel_id -> 已实现的 profile / DSN resolver -> 当前酒店的数据源
```

因此，一个机器人账号可以是某酒店的专属入口，但不能仅根据账号 ID 选择数据库；未绑定群或未解析到唯一酒店时必须拒绝业务请求。

---

## 二、原来的配置在哪？

配置分 6 类，但当前单酒店 runtime 还需要先完成多酒店代码改造；**不能只改服务器配置就上线第二家酒店**：

### 配置文件总览

| # | 文件路径 | 管什么 |
|---|---------|--------|
| ① | `/root/.openclaw/openclaw.json` | 飞书账号（appId/appSecret）+ 消息路由规则 |
| ② | `/etc/hotel-ota-ai/hotel-ota.env` | 受控环境变量/密钥注入、日志路径、各种开关 |
| ③ | `/etc/hotel-ota-ai/database-source.json` | 数据库表结构映射、酒店名别名 |
| ④ | `/etc/hotel-ota-ai/feishu-role-map.json` | 谁能用机器人（用户权限）、群绑定关系 |
| ⑤ | `/etc/hotel-ota-ai/market-source.json` | 酒店的天气/节假日/活动市场数据配置 |
| ⑥ | `/etc/hotel-ota-ai/s14-source.json` | S14诊断的数据源配置（Excel路径等） |

先完成第九章的“代码前置条件”，再按下面的配置步骤接入新酒店。

---

## 三、文件①：openclaw.json（飞书账号和路由）

**文件路径**：`/root/.openclaw/openclaw.json`

### 原来配置了什么？

这个文件有两块跟机器人有关：

**第1块：飞书账号列表**（`channels.feishu.accounts`）

每个机器人在这里登记，相当于给机器人上户口：

```json
"channels": {
  "feishu": {
    "accounts": {
      "s14-ext": {                          // ← S14诊断机器人的账号ID
        "enabled": true,
        "appId": "${FEISHU_S14_APP_ID}",           // 仅示例：由密钥管理注入
        "appSecret": "${FEISHU_S14_APP_SECRET}",   // 不在本文或 Git 中保存真实值
        "requireMention": true,            // ← 需要@机器人才回复
        ...
      },
      "default-hotel-ota-ai": {            // ← 酒店数字员工的账号ID
        "enabled": true,
        "appId": "${FEISHU_CHIEF_APP_ID}",
        "appSecret": "${FEISHU_CHIEF_APP_SECRET}",
        "requireMention": true,
        ...
      },
      "s14-ext-test": { ... },             // ← 测试账号
      "hotel-ota-ai-test": { ... }         // ← 测试账号
    }
  }
}
```

**第2块：路由规则**（`bindings`）

告诉系统"哪个账号的消息交给哪个后台处理"：

```json
"bindings": [
  { "type": "route", "agentId": "s14-operation-diagnosis",   // S14诊断后台
    "match": { "channel": "feishu", "accountId": "s14-ext" } },
  { "type": "route", "agentId": "s14-operation-diagnosis",
    "match": { "channel": "feishu", "accountId": "s14-ext-test" } },
  { "type": "route", "agentId": "hotel-ota-chief",          // 数字员工后台
    "match": { "channel": "feishu", "accountId": "default-hotel-ota-ai" } },
  { "type": "route", "agentId": "hotel-ota-chief",
    "match": { "channel": "feishu", "accountId": "hotel-ota-ai-test" } }
]
```

### 多酒店后怎么改？

每加一个酒店，**在这两块各加2段**（数字员工1段 + S14诊断1段）：

**第1块加2个新账号**（在accounts里追加）：
```json
"hotela-chief": {                           // 新酒店的数字员工账号ID（自己起）
  "enabled": true,
  "groupPolicy": "allowlist",
  "appId": "cli_xxxxx",                     // 新飞书应用的App ID
  "appSecret": "xxxxx",                     // 新飞书应用的App Secret
  "requireMention": true,
  "dmPolicy": "open",
  "groupAllowFrom": ["*"],
  "allowFrom": ["*"]
},
"hotela-s14": {                             // 新酒店的S14诊断账号ID（自己起）
  "enabled": true,
  "groupPolicy": "allowlist",
  "appId": "cli_yyyyy",                     // 另一个新飞书应用的App ID
  "appSecret": "yyyyy",                     // 另一个新飞书应用的App Secret
  "requireMention": true,
  "dmPolicy": "open",
  "groupAllowFrom": ["*"],
  "allowFrom": ["*"]
}
```

**第2块加2条路由**（在bindings数组里追加）：
```json
{ "type": "route", "agentId": "hotel-ota-chief",
  "match": { "channel": "feishu", "accountId": "hotela-chief" } },
{ "type": "route", "agentId": "s14-operation-diagnosis",
  "match": { "channel": "feishu", "accountId": "hotela-s14" } }
```

> **规则**：`*-chief` → `hotel-ota-chief`（数字员工后台）；`*-s14` → `s14-operation-diagnosis`（S14后台）

---

## 四、文件②：hotel-ota.env（数据库连接、环境变量）

**文件路径**：`/etc/hotel-ota-ai/hotel-ota.env`

### 原来配置了什么？

原来只有璞悦酒店一套配置，很多连接串直接写死了连璞悦：

```bash
# ===== 数据库连接 =====
# 主数据库连接（示意；真实值只写入密钥管理或私有环境文件）
HOTEL_OTA_DB_DSN_PUYUE=${SECRET_PUYUE_MAIN_DSN}
HOTEL_OTA_DB_DSN=${SECRET_PUYUE_MAIN_DSN}  # 仅单酒店兼容值；多酒店运行不得把它当跨酒店回退

# S14诊断数据库连接（也是璞悦）
S14_DB_DSN=${SECRET_PUYUE_S14_DSN}

# 调价任务库（🔴写死璞悦！多酒店后改为按酒店路由）
HOTEL_OTA_PRICE_TASK_DB_DSN=mysql+pymysql://...@127.0.0.1:3306/hotel_puyue?...

# 评论任务库（🔴写死璞悦！多酒店后改为按酒店路由）
HOTEL_OTA_REVIEW_TASK_DSN=mysql+pymysql://...@127.0.0.1:3306/hotel_puyue?...

# ===== 运行控制 =====
# 当前使用哪个数据库profile（多酒店后不再需要手动切换，系统自动按酒店选）
HOTEL_OTA_DB_PROFILE=puyue_mysql_prod

# 认证插件管哪些账号（只管数字员工，不管S14）
HOTEL_OTA_FEISHU_AUTH_ACCOUNTS=default-hotel-ota-ai,hotel-ota-ai-test

# ===== 路径配置 =====
# 日志目录（多酒店后按酒店分子目录）
HOTEL_OTA_LOG_DIR=/var/log/hotel-ota-ai

# S14报告输出路径
S14_REPORT_OUTPUT_DIR=/var/lib/ota-marketing-diagnosis/reports
S14_PUBLIC_BASE_URL=http://47.108.200.194:8081/s14-reports

# ===== S14卡片回调服务 =====
S14_FEISHU_CALLBACK_HOST=127.0.0.1
S14_FEISHU_CALLBACK_PORT=8091
S14_FEISHU_CALLBACK_PATH=/s14/feishu/card-callback

# 飞书应用凭证（用于回调发送消息，当前是测试机器人的，多酒店后按酒店分）
FEISHU_APP_ID=${FEISHU_CALLBACK_APP_ID}
FEISHU_APP_SECRET=${FEISHU_CALLBACK_APP_SECRET}
```

### 多酒店后怎么改？

每加一个酒店，准备以下 DSN/密钥资产；**仅配置这些变量不会自动生效**，必须先完成第九章的 resolver 改造：

**1. 加新酒店的所有数据库连接串**（不止主库！每个功能都要配）：
```bash
# ===== 新酒店A的数据库连接 =====
# 主业务库（最重要，S01-S07/S15-S17用）
HOTEL_OTA_DB_DSN_HOTELA=${SECRET_HOTELA_MAIN_DSN}

# S14诊断库（一般和主库同一个）
S14_DB_DSN_HOTELA=${SECRET_HOTELA_S14_DSN}

# 调价任务库（S06调价写入，🔴必须配，否则会写到璞悦！）
HOTEL_OTA_PRICE_TASK_DB_DSN_HOTELA=${SECRET_HOTELA_PRICE_TASK_DSN}

# 评论任务库（S13评论回复写入，🔴必须配，否则会写到璞悦！）
HOTEL_OTA_REVIEW_TASK_DSN_HOTELA=${SECRET_HOTELA_REVIEW_TASK_DSN}

# 促销控制库（S11促销执行写入，🔴必须配）
HOTEL_OTA_PROMOTION_CONTROL_DSN_HOTELA=${SECRET_HOTELA_PROMOTION_CONTROL_DSN}
```

> **⚠️ 重要安全提示**：调价执行（S6）、评论回复（S13）、促销执行（S11）是写入操作。当前单酒店代码仍存在全局 DSN/璞悦 DSN 回退路径，不能据此宣称“新酒店缺 DSN 一定会拒绝”。完成 resolver 改造后，必须规定：非当前酒店的 DSN、profile 或 outbox 缺失时一律 fail closed，绝不回退到璞悦。

**2. 认证账号列表追加新数字员工账号**（只加chief，不加s14）：
```bash
# 原来：
HOTEL_OTA_FEISHU_AUTH_ACCOUNTS=default-hotel-ota-ai,hotel-ota-ai-test
# 改为：
HOTEL_OTA_FEISHU_AUTH_ACCOUNTS=default-hotel-ota-ai,hotel-ota-ai-test,hotela-chief
```

**3. S14卡片回调需要每个酒店一组凭证**：
```bash
# 新酒店A的S14机器人凭证（用于卡片按钮回调后发消息）
S14_BOT_HOTELA_APP_SECRET=新酒店S14机器人的appSecret
S14_BOT_HOTELA_VERIFICATION_TOKEN=新酒店S14机器人的verification_token
```

> **实现要求**：新增 `hotel_id -> profile -> dsn_env` resolver 后，才允许保留璞悦的单酒店兼容变量；生产多酒店请求若未解析到 hotel_id 或 profile，必须停止，不能使用 `HOTEL_OTA_DB_DSN`、`HOTEL_OTA_DB_PROFILE` 或任何璞悦变量作为通用默认值。

---

## 五、文件③：database-source.json（数据库表映射）

**文件路径**：`/etc/hotel-ota-ai/database-source.json`

### 原来配置了什么？

原来只配了璞悦一个profile，定义了27张表的名字和字段映射：

```json
{
  "default_profile": "puyue_mysql_prod",
  "profiles": {
    "puyue_mysql_prod": {
      "db_kind": "mysql",
      "dsn_env": "HOTEL_OTA_DB_DSN_PUYUE",
      "mapping_version": "puyue_27_tables_v1",
      "hotel_ids": {
        "puyue": {
          "hotel_name": "星锋电竞酒店（贵州大学花溪公园店）",
          "display_name": "璞悦·奢电竞酒店(贵阳花溪公园店)",
          "aliases": ["璞悦·奢电竞酒店(贵阳花溪公园店)", "星锋电竞酒店..."]
        }
      },
      "tables": { ... 27张表名映射 ... },
      "columns": { ... 27张表的字段映射 ... }
    }
  }
}
```

这个文件告诉系统：数据库里每张表叫什么名字、每个字段叫什么、酒店在PMS系统里叫什么名字。

### 多酒店后怎么改？

**如果新酒店的表结构和璞悦一样**（用的是同一套 PMS/OTA 采集系统），可以继承璞悦的表映射，不必重复写全部表字段。`inherits` 已由当前 mapping adapter 支持；但下方的 `hotel_profile_map` 仍是**待实现的配置契约**，必须先由 runtime resolver 读取，不能只把它写进 JSON 就认为会生效：

```json
{
  "default_profile": "puyue_mysql_prod",
  "hotel_profile_map": {                          // ← 新增这一段
    "puyue": "puyue_mysql_prod",
    "hotela": "hotela_mysql_prod"
  },
  "profiles": {
    "puyue_mysql_prod": { ... 原来保持不变 ... },
    "hotela_mysql_prod": {                        // ← 新增酒店A的profile
      "inherits": "puyue_mysql_prod",            // 继承璞悦的表映射
      "db_kind": "mysql",
      "dsn_env": "HOTEL_OTA_DB_DSN_HOTELA",      // 用.env里新酒店的DSN
      "mapping_version": "hotela_27_tables_v1",
      "hotel_ids": {
        "hotela": {
          "hotel_name": "新酒店A在PMS里的名字",
          "display_name": "新酒店A的展示名",
          "aliases": ["可能的别名1", "别名2"]
        }
      }
      // 不用写tables和columns！因为inherits已经继承了璞悦的
    }
  }
}
```

**如果新酒店表结构不一样**，就需要像 `puyue_mysql_prod` 那样完整写 tables 和 columns。无论哪种情况，上线前都必须验证关键表可用，并确认 profile 的 DSN 只指向该酒店独立数据库；表内存在 `hotel_id` 时仍应作为防御性一致性校验。缺 `hotel_id` 的 legacy 表不得成为跨库拼接数据的依据。

---

## 六、文件④：feishu-role-map.json（用户权限）

**文件路径**：`/etc/hotel-ota-ai/feishu-role-map.json`

### 原来配置了什么？

这个文件管"谁能使用机器人"，有3部分：

```json
{
  "global_admin_principal_ids": ["admin_zhang", "admin", "admin_2"],  // 全局管理员，能管所有酒店

  "users": [                        // 所有用户列表（飞书open_id → 内部ID）
    { "name": "张老板", "principal_id": "admin_zhang", "open_id": "ou_933f1f..." },
    { "name": "李经理", "principal_id": "owner_hotel_li", "open_id": "ou_1f88f7..." },
    ...
  ],

  "hotel_memberships": [            // 哪个用户属于哪个酒店、什么角色
    { "principal_id": "owner_hotel_li", "hotel_id": "puyue", "role": "owner" },
    { "principal_id": "admin_2", "hotel_id": "puyue", "role": "owner" },
    ...
  ],

  "group_chat_bindings": [          // 哪个飞书群绑定到哪个酒店
    {
      "chat_id": "oc_xxxxx",        // 飞书群ID
      "chat_name": "璞悦酒店管理群",
      "hotel_id": "puyue"
    }
  ]
}
```

**角色说明**：
- `global_admin`：全局管理员，能看所有酒店
- `owner`：酒店老板/店长，能操作本酒店所有功能
- `operator`：前台/运营，部分操作需审批
- `frontdesk`：前台，只能看快照

### 多酒店后怎么改？

**1. 新酒店的用户加到 `users` 数组**（如果不在里面的话）：
```json
{ "name": "王老板", "principal_id": "owner_hotel_wang", "open_id": "ou_xxxxx" }
```

**2. 新酒店的人员关系加到 `hotel_memberships`**：
```json
{ "principal_id": "owner_hotel_wang", "hotel_id": "hotela", "role": "owner" }
```

**3. 新酒店的群绑定加到 `group_chat_bindings`**：
```json
{
  "chat_id": "oc_newgroup123",
  "chat_name": "酒店A管理群",
  "hotel_id": "hotela"
}
```

> **注意**：`feishu-role-map.json` 是 bootstrap/同步材料；生产运行时的权威来源是 SQLite Active Auth（`auth_principals`、`hotel_memberships`、`chat_bindings/group_chat_bindings`）。`bot_account_id` 不是当前 SQLite 群绑定 schema 的安全范围字段，不应作为授权依据。全局管理员权限也必须由 SQLite 的 active auth 事实确认。

---

## 七、文件⑤：market-source.json（市场数据配置）

**文件路径**：`/etc/hotel-ota-ai/market-source.json`

### 原来配置了什么？

```json
{
  "hotels": {
    "puyue": {
      "weather": {
        "latitude": "26.43",           // 酒店纬度
        "longitude": "106.67",         // 酒店经度
        "display_location": "贵阳花溪",
        "location": "花溪公园"
      },
      "events": { "table": "meituan_ota_nearby_event", ... },
      "holiday": { ... },
      "regional_heat": { "weights": { ... } }
    }
  }
}
```

这个文件告诉系统酒店的经纬度（查天气用）、周边活动数据源等。

### 多酒店后怎么改？

在 `hotels` 里追加新酒店的配置：
```json
"hotels": {
  "puyue": { ... 原来不变 ... },
  "hotela": {
    "weather": {
      "latitude": "新酒店纬度",
      "longitude": "新酒店经度",
      "display_location": "城市区域",
      "location": "具体位置"
    },
    "events": { "table": "meituan_ota_nearby_event" },
    "holiday": { "enabled": true },
    "regional_heat": { "weights": { "competitor": 0.4, "weather": 0.2, "holiday": 0.4 } }
  }
}
```

---

## 八、文件⑥：s14-source.json（S14数据源配置）

**文件路径**：`/etc/hotel-ota-ai/s14-source.json`

### 原来配置了什么？

```json
{
  "hotels": {
    "puyue": {
      "s14_sources": {
        "monthly_excel": {
          "source_mode": "excel",
          "enabled": true,
          "path": "/var/lib/hotel-ota-ai/s14/puyue/monthly.xlsx"
        },
        "readonly_mysql": {
          "source_mode": "mysql",
          "enabled": true,
          "profile": "puyue_mysql_prod"
        }
      }
    }
  }
}
```

这个文件只在 S14-EXT 独立服务实际支持该 source_key 时登记数据源。当前主 runtime 的 S14 是对既有能力结果的编排，不能把任意私有 MySQL/Excel 路径当成通用配置；S14-EXT 的回调、报告目录和应用映射需按独立服务契约单独验收。

### 多酒店后怎么改？

在 `hotels` 里追加新酒店：
```json
"hotels": {
  "puyue": { ... 原来不变 ... },
  "hotela": {
    "s14_sources": {
      "monthly_excel": {
        "source_mode": "excel",
        "enabled": true,
        "path": "/var/lib/hotel-ota-ai/s14/hotela/monthly.xlsx"
      },
      "readonly_mysql": {
        "source_mode": "mysql",
        "enabled": true,
        "profile": "hotela_mysql_prod"       // ← 指向database-source.json里的profile名
      }
    }
  }
}
```

---

## 九、新增一个酒店的完整步骤（速查表）

假设要接入一个新酒店，酒店ID叫 `newhotel`，酒店名叫"XX酒店"：

### 第零步：完成代码前置条件（必须先于生产配置）

1. 实现并测试 `hotel_id -> profile -> dsn_env` resolver；每次查询、任务写入和回查均显式携带已鉴权的 `hotel_id`。
2. 移除 S8-S13、S5/S6 和促销/评论/价格任务路径中的璞悦全局 DSN 回退；缺当前酒店 DSN、profile 或 outbox 时 fail closed。
3. 为启动自检增加每酒店 profile、DSN、表映射、启用渠道、任务表，以及“`hotel_id` 与独立数据库连接一致”的校验。
4. 用第 2 家测试酒店完成跨酒店拒绝、读库、写入、插件拾取和回查测试；通过后才接入生产酒店。

> 未完成以上前置条件时，本章只能用于准备资料，**不得**创建生产路由、群绑定或执行任何调价/评论/推广写入。

### 第一步：在飞书开放平台创建2个应用

1. 打开 https://open.feishu.cn/app
2. **按业务需要创建应用1**：名称"XX酒店收益助手"。每酒店两个机器人是品牌/流程选择，不是 runtime 自动隔离的替代方案。
   - 添加机器人能力
   - 开通权限：`im:message`、`im:message:send_as_bot`、`im:chat`
   - 事件订阅：选择"使用长连接接收事件"，添加 `im.message.receive_v1`
   - 发布版本，等审核通过
   - **记录**：App ID、App Secret
3. **按 S14-EXT 独立服务需要创建应用2**：名称"XX酒店S14诊断助手"；先确认该服务已支持多应用回调识别。
   - 添加机器人能力
   - 开通权限：`im:message`、`im:message:send_as_bot`、`im:chat`、`im:resource`
   - 事件订阅：
     - 长连接添加 `im.message.receive_v1`
     - 配置HTTP回调（卡片按钮用）：请求地址 `https://你的域名/s14/feishu/card-callback`
   - 发布版本，等审核通过
   - **记录**：App ID、App Secret、Verification Token、Encrypt Key

### 第二步：修改服务器配置文件

按上面的说明，依次修改6个文件：

| 顺序 | 文件 | 做什么 | 关键项 |
|-----|------|--------|--------|
| 1 | 代码与测试 | 实现 resolver、去除璞悦回退、增加跨酒店测试 | 必须先完成 |
| 2 | `hotel-ota.env` | 注入新酒店独立数据库的 DSN/密钥，由 resolver 统一选择 | 不写真实值到文档/Git |
| 3 | `openclaw.json` | 增加实际需要的账号和 bindings 路由 | App ID/App Secret 仅密钥管理 |
| 4 | `database-source.json` | 加新 profile（可 inherits），并让 resolver 使用该 profile | hotel_id/profile/dsn_env 一致 |
| 5 | SQLite Active Auth | 经 BIND / ROLE 受控流程写入群绑定与成员角色 | 可信 chat_id、成员身份 |
| 6 | `market-source.json` | 加新酒店的经纬度、节假日和市场配置 | latitude/longitude |
| 7 | `s14-source.json` | 仅在 S14-EXT 实现支持时登记 source_key/profile | 单独验收 |

> **⚠️ 配置检查清单（上线前必须确认）**：
> - [ ] resolver 已发布并能为新酒店解析唯一 profile / DSN？
> - [ ] 所有读写路径已移除璞悦回退，缺 current-hotel DSN 时会 fail closed？
> - [ ] 新酒店 DSN 是否仅指向该酒店的独立数据库，且没有复用其他酒店数据库？
> - [ ] openclaw.json里两个新账号的AppID/AppSecret正确？
> - [ ] database-source.json里新profile的dsn_env指向正确的环境变量名？
> - [ ] SQLite Active Auth 中群绑定的 hotel_id、成员 membership 和角色正确？
> - [ ] 飞书账号路由、认证插件账号清单、S14-EXT 回调映射均已按实际部署验证？

### 第三步：创建目录

```bash
mkdir -p /var/log/hotel-ota-ai/newhotel/
mkdir -p /var/lib/hotel-ota-ai/s14/newhotel/
mkdir -p /var/lib/hotel-ota-ai/s14/reports/newhotel/
mkdir -p /var/lib/hotel-ota-ai/experience/newhotel/
mkdir -p /var/lib/ota-marketing-diagnosis/reports/newhotel/
```

### 第四步：通过受控流程完成认证与群绑定

不要直接执行 `INSERT INTO feishu_accounts`：当前 SQLite schema 没有该表，且手工 SQL 会绕过审计。

1. 由可信管理员使用 BIND 流程把已验证的群 `chat_id` 绑定到 `newhotel`；未绑定群保持拒绝。
2. 由 ROLE 流程把可信飞书身份写入 `auth_principals` 和 `hotel_memberships`，并在 `newhotel` 范围内授予 owner/operator/frontdesk。
3. 检查 SQLite Active Auth 的绑定状态和审计记录；JSON `feishu-role-map.json` 只用于 bootstrap/同步，不替代运行时校验。

### 第五步：按已验证的部署单元发布与重启

```bash
按变更单发布 runtime 与独立 S14-EXT 服务；仅重启实际受影响的服务，并保留回滚点。
```

### 第六步：飞书端配置

1. 在飞书里创建酒店管理群
2. 把"XX酒店收益助手"和"XX酒店S14诊断助手"两个机器人都拉进群
3. 不要把其他酒店的业务机器人作为可处理业务的入口加入该群；即使误加入，也必须因群绑定与 hotel_id 校验而无法跨酒店取数。
4. 在群里 @XX酒店收益助手 发"菜单"测试
5. @XX酒店S14诊断助手 发"S14诊断"测试
6. 检查 S2/S5/S6/S8-S13/S14-EXT（适用时）均只返回新酒店的数据；再验证跨酒店请求被拒绝、任务写入及回查 hotel_id 正确。

---

## 十、常见问题

**Q：新酒店的数据库表结构和璞悦不一样怎么办？**
A：需要在 `database-source.json` 里完整写 tables 和 columns 映射，不能用 inherits。这是技术工作，需要开发人员配合。

**Q：一个群里两个机器人会抢着回复吗？**
A：不会。系统通过账号ID路由消息——用户@哪个机器人，就只有那个机器人回复。而且两个机器人的触发词不同：数字员工响应"菜单/调价/快照"等日常指令，S14响应"S14诊断/运营诊断"。

**Q：可以把璞悦和新酒店的机器人拉到同一个群吗？**
A：**绝对不可以！** 一个群只能有同酒店的两个机器人。否则会导致消息串扰。

**Q：怎么知道新酒店的飞书群 chat_id？**
A：把机器人拉进群后，在群里随便发一条消息 @机器人，机器人会在日志中打印 chat_id。或者用飞书管理后台查看。

**Q：改完配置需要重启吗？**
A：需要。`openclaw gateway restart` 重启主服务。如果改了S14相关的环境变量，也需要重启S14回调服务。

**Q：S14的HTTP回调地址所有酒店共用一个吗？**
A：是的。所有酒店的S14机器人卡片回调都发到同一个地址（`https://域名/s14/feishu/card-callback`），服务端根据回调消息里的app_id自动区分是哪个酒店。飞书后台每个S14应用都配置同一个回调URL即可。

**Q：日志在哪看？**
A：
- 主数字员工日志：`/var/log/hotel-ota-ai/酒店ID/`
- S14日志：看OpenClaw的agent日志
- 系统服务日志：`journalctl -u openclaw-gateway`

**Q：怎么确认机器人连的是对的数据库，不会串到璞悦？**
A：不能只看回复名称。上线测试必须同时验证：
1. resolver 对该群解析的 `hotel_id`、profile 和 DSN 为新酒店；
2. S2/S5/S6/S8-S13 的真实房量、商品、评论、任务写入及回查与新酒店库一致；
3. 使用未绑定群和无该酒店 membership 的用户发起同类请求，必须被拒绝；
4. S14-EXT（如启用）报告标题、数据源和回调均为新酒店。

**Q：如果新酒店的DSN没配对，会不会把调价指令发到璞悦？**
A：目标行为是“不会”：完成多酒店 resolver 改造后，非当前酒店找不到 DSN/profile/outbox 必须直接拒绝。**当前单酒店代码尚未全面满足此条件**，因此在改造和跨酒店写入测试完成前，禁止对第 2 家酒店开放 S6/S11/S13 写入。

**Q：新酒店需要独立的 MySQL 数据库吗？**
A：需要。本方案的既定部署模型是“每酒店一个独立数据库”，可位于同一 MySQL 实例，也可位于不同实例；但数据库名和 DSN 必须独立。resolver 只能返回当前已鉴权酒店的 DSN，绝不能复用其他酒店数据库作为回退。表中若有 `hotel_id`，仍应核对其与当前酒店一致，作为额外防串库保护。

**Q：每个酒店的S8-S13等技能需要单独配DSN吗？**
A：运行时不应让每个技能自己拼环境变量。推荐由统一 resolver 按 `hotel_id` 返回当前酒店的主库与可选 writer/outbox DSN；若这些表位于同一酒店数据库，可以返回同一 DSN。S8-S13 的前提是其 Source 构造器已接收 resolver 结果，不能保留璞悦硬编码回退。
