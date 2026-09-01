---
name: s01-control-config
description: "S1 顶层配置：用于初始化、查看、更新酒店档案、房型、渠道、价格边界、角色权限、skill 开关和审批策略。触发语：初始化配置、查看酒店配置、设置价格底线、权限配置、skill开关。"
---

# S1 顶层配置


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户要初始化酒店数字员工、查看或修改酒店配置、设置价格底线/上限、配置角色权限、打开或关闭某个 skill 时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`
- `{baseDir}/../_shared/operating-policy.md`

## 核心职责

- 维护酒店档案：`hotel_id`、酒店名称、PMS 厂商、Beyondh `OrgId`、时区。
- 维护房型、OTA 渠道、价格底线、价格上限、单次涨降幅限制。
- 维护老板、运营、前台三类角色权限。
- 维护各酒店可用 skill 开关和关闭原因。
- 维护执行审批策略。默认规则：调价、房量、房态、推广、公开评论回复都必须 admin/owner 审批。

## 执行流程

1. 识别目标酒店；演示酒店默认使用 `puyue`。
2. 如果运行时数据库不存在，先提示或执行初始化：

```bash
python runtime/hotel_ota_runtime.py init-db
python runtime/hotel_ota_runtime.py seed-demo
```

3. 返回当前生效配置、缺失配置、可用 skill、审批策略。
4. 不在聊天中索要或展示密钥、密码、验证码；只提示用户把密钥放进 `config/env.example` 对应环境变量。

## 输出要求

按共享标准输出，并重点包含：

- `config_status`
- `missing_config`
- `enabled_skills`
- `approval_policy`
- `next_setup_steps`

## 安全规则

- 不得把 `ChannelKey`、`AppKey`、`Sign`、PMS/OTA 密码或验证码写入回复。
- 不得放开真实执行权限，除非老板明确确认并符合共享审批规则。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N003.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 控制面配置 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py env-check --hotel-id <hotel_id>
```

Allowed runtime commands: `init-db`, `seed-demo`, `env-check`, `auth-bootstrap-sync`, `role-map-preview`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

### 数据来源要求
runtime CLI and controlled database-query only.

### 生产环境禁止事项和 data_gap 规则

- 生产 Feishu 必须使用 verified role；需要时由 HOTEL_OTA_REQUIRE_VERIFIED_ROLE 强制
- 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API
- demo/sample/synthetic/hardcoded 数据不得用于 production Feishu 业务结论
- 缺少必要数据必须返回 data_gap，不得编造成 0 或继续给正式结论
- 禁用渠道不得参与读取、分析和展示
- agent 不得自己编造 runtime 没有返回的结论。

### 飞书输出规则

- 生产飞书输出必须遵守 feishu-output-gate 语义
- 不得输出 DSN、token、服务器私有路径、原始订单行、payload_hash 或内部 request payload；no private path

### 写操作和审批规则

- runtime 未返回 write_performed=true、affected_rows>0、config_change_applied=true 或 audit_id 时，不得声称已执行、已删除、已写入或已配置
- 本 skill 只按 runtime 证据输出结论，不扩展到未授权动作。

### 常见用户说法和处理方式

- User says "当前数据源": route to `control_config` and run `env-check`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
