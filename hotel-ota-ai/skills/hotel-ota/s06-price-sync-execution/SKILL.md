---
name: s06-price-sync-execution
description: "S6 房价同步执行：admin/owner 审批后通过渠道适配层 dry-run 或执行房价同步，并回读校验与记录日志。触发语：执行调价、同步房价、确认执行、调价dry-run、预览执行。"
---

# S6 房价同步执行


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

仅当用户明确要求调价 dry-run、预览执行、或执行已审批调价动作时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`
- `{baseDir}/../_shared/operating-policy.md`
- `{baseDir}/../_shared/channel-api-map.md`

## 安全规则

- 默认只做 `dry_run`。
- 没有 admin/owner 审批不得真实执行。
- 价格低于底价、高于上限、超过单次涨降幅限制时必须阻断。
- 不得暴露 Beyondh、美团、订单来了密钥、签名、密码、验证码。
- 真实调用还必须满足对应渠道 live 开关，例如 `BEYONDH_ENABLE_LIVE=1`。

## 渠道写接口参考

- 优先价格写入：`Price.SetPriceByRoomTypeId`。
- 固定房价码写入：`Price.SetPriceByRateCode`。
- 美团商家侧写接口待账号权限确认；未确认前只生成平台人工任务或 RPA 任务。
- 订单来了可参考 PMS/直连中台价格、库存、订单接口；P0/P1 只做 dry-run 请求构造和字段归一化。
- 房量写入接口待客户或服务器文档确认后再启用。

## 执行流程

1. 校验审批人、角色、酒店、房型、渠道、日期、价格。
2. 先展示 dry-run 请求（**同房型多商品时必须用 `--ota-product-id` 指定要调的商品**，否则会被 `price_task_requires_ota_product_id` 拒绝）：

```bash
python runtime/hotel_ota_runtime.py execute-price --hotel-id puyue --room-type-id <统一房型ID> --ota-product-id <OTA商品ID> --channel Mtop --normal-price 159 --weekend-price 189 --begin-date 2026-06-01 --end-date 2026-06-01 --approved-by owner --dry-run
python runtime/hotel_ota_runtime.py adapter-request --adapter meituan --path /pms/priceinve/getRoomPrice --biz-content '{"hotelId":600000001,"channel":"MeiTuanEBK","roomTypeIds":["KING"]}'
python runtime/hotel_ota_runtime.py adapter-request --adapter dindanll --path /open/pms/third/ari/price --biz-content '{"hotelNum":10001,"roomTypeCodeList":[9001],"rateCode":30}'
```

3. 真实执行时必须设置对应渠道 live 开关且去掉 `--dry-run`。
4. 记录请求摘要、响应码、失败原因和 fallback。
5. API 失败时，通过 S3 生成 RPA 或前台人工任务。

## 输出要求

返回 dry-run/执行结果、渠道来源、API 方法、脱敏请求摘要、响应码、失败原因、fallback 指令。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N016.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 价格同步执行 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py execute-price --hotel-id <hotel_id>
```

Allowed runtime commands: `execute-price`, `price-task-history`, `adapter-request`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

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
- price_guard and mapping_ready required before pricing candidates or execution.
- dry_run_first and approval_required before any write or external execution.

### 常见用户说法和处理方式

- User says "调价 dry-run": route to `price_sync_execution` and run `execute-price`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
