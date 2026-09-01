---
name: s12-reputation-management
description: "S12 口碑管理：监控评分、差评、回复率、好评任务和口碑诊断。触发语：口碑、评分、差评、回复率、好评任务。"
---

# S12 口碑管理


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户询问评分、差评、回复率、好评任务、HOS/PSI 口碑项、口碑风险时，使用本 skill。

“昨日新增了几条评论 / 昨日评论数 / 昨日新增评论”以及“近两天 / 近三天新增评论”属于 S12 的评论增量统计子场景：必须按 `review_time` 的自然日窗口读取真实评论明细，展示新增量及可用的回复率、好评率等统计；近多日统计还应按日拆分。不得改走 demo、历史样例或通用口碑诊断的演示数据。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`

## 核心职责

- 监控评分变化、评论数量和差评风险。
- 读取美团评分、差评率、评价内容、差评跟进状态等参考字段；API 不可用时支持截图/导出上传。
- 识别紧急差评和公共口碑风险。
- 跟踪回复率和好评任务进度。
- 推荐服务、内容和前台跟进任务。
- 将需要回复的评论交给 S13。
- 统计昨日或近两/三天新增评论、统计窗口内评论的当前回复率、好评率、低分率和来源差评；回复率的分母只能是该统计窗口内回复状态可识别的新增评论，不代表窗口内当日完成回复率。

## 执行流程

1. 采集 OTA 评分/评论数据、截图或导出文件。
2. 按情绪和紧急程度分类评论。
3. 识别高频问题：服务、设施、卫生、噪音、价格、退款、入住。
4. 给出负责人、期限和跟进动作。

评论增量统计的“重新执行一下”仅在飞书回复上下文能识别为上一条昨日或近多日新增评论请求时，才重跑相同的真实只读查询；没有该上下文时应请用户重新发送完整问题，不能猜测为 demo 或历史查询。

## 输出要求

返回口碑记分卡、风险项、任务、需要 S13 起草回复的评论。

## 安全规则

- 不公开发布评论回复。
- 涉及差评升级时优先生成处理任务。
- 普通飞书正文只写“S12 口碑管理”或业务结论；不得输出 intent、runtime command、内部路由名、数据链路或 demo 回退诊断。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N008.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 口碑管理 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py reputation-diagnosis --hotel-id <hotel_id>
```

Allowed runtime commands: `reputation-diagnosis`, `database-query`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

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

- User says "看一下差评问题": route to `reputation_management` and run `reputation-diagnosis`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
