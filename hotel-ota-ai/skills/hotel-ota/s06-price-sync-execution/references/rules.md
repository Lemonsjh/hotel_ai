# S6 房价同步执行规则

## 核心输入字段
- `approval_id`
- `approved_by`
- `room_type_id`
- `ota_product_id`（按商品精确调价：同房型多商品时必填）
- `channel`
- `normal_price`
- `weekend_price`
- `begin_date`
- `end_date`
- `ota_base_price`
- `ota_activity_discount_factor`
- `ota_estimated_final_price`
- `pms_price_reference_only`
- `price_floor`
- `price_ceiling`

## 价格口径
- S6 执行预览和写接口目标是 OTA 后台门市价。
- `normal_price` / `NormalPrice` 等同于 `ota_base_price`。
- `ota_estimated_final_price` 只用于向业务解释外网预估价，不写入 PMS。
- `pms_price_reference_only` 只允许作为参考字段，不得进入 Beyondh 写接口 BizContent。
- dry-run 回复必须展示：后台价、活动折扣系数、预估外网价、底价/最高价守卫、审批状态。

## 判断逻辑
1. 无 `auth_context` 或发送人未授权时不执行。
2. 默认 dry-run。
3. 非 dry-run 必须同时具备 `approval_id`、`approved_by` 和 `admin/owner` 审批角色。
4. 必须校验本地审批记录存在、状态为 approved、动作类型匹配、审批数据仍为 `fresh/current`。
5. 必须通过价格底线、最高价、单次涨降幅和 live 开关后，才允许真实写入。
6. **按商品精确调价**：同房型下有多个 OTA 商品（挂牌/团购/钟点，价差大）时必须传 `ota_product_id` 只调指定商品；不传且多商品时写入被拒（`price_task_requires_ota_product_id`），不得把一个目标价灌给全部商品覆盖团购价。护栏按该商品真实当前价校验。
7. 当前阶段只做建议和 dry-run，不做无审批自动执行。
8. 失败时输出人工处理建议，不输出密钥、DSN、完整请求体或原始配置。

## 角色权限
- `admin` 和 `owner` 可审批并进入真实执行校验。
- `operator` 只能生成调价 dry-run 和发起审批。
- `frontdesk` 不能预览或执行调价。
- `guest` 不触发 S6。
- 不能只凭 `approved_by` 文本放行，必须有审批记录和审批人角色。
- 无 `approval_id` 的“同意/拒绝”只追问审批编号，不执行、不改文件、不关联其他话题。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- 旧数据、sample/demo 数据不得进入 S6 live 执行。
- PMS 价不是 S6 默认写入目标；除非后续业务明确改口径并更新审批规则。

## V27 可施工算法规格

# 算法来源

- 对应节点：N016 / S6 房价同步执行
- 对应 Agent：A4
- 对应 BP：P1
- 对应源文件：`references/source/source_manifest.yaml`
- 对应字段契约：`contracts/node_io_contract.yaml`
- 对应 runtime algorithm_rules：`runtime/algorithm_rules/execution_guard.yaml`

# 输入字段

## hard_required
缺失则阻断：hotel_id, room_type_id, channel, candidate_price, approval_id, freshness_status, data_source_type, source_capability, live_allowed, approval_data_allowed

## soft_required
缺失可继续但必须输出 data_gap：floor_price, ceiling_price, max_single_change_pct, readback_check, live_switch

## optional
增强判断，不阻断主链路：none

## candidate
候选字段，不稳定，不用于 live：none

## blocked_for_live
可用于诊断或 dry-run，不得用于正式执行：demo_data, sample_data, stale, missing_date, manual_chat, manual_without_audit

# 算法步骤

1. Accept only S5-approved decision payload; never recalculate price logic.
2. Validate auth role, approval_id, freshness_status, business_status, and channel live flag.
3. Return dry_run request summary by default.
4. Block live execution for demo/sample/stale/missing_date or missing admin/owner approval.

# 判断规则

阈值与分级来自 `runtime/algorithm_rules/execution_guard.yaml`：`{"dry_run_default": true, "demo_live_allowed": false, "operator_live_allowed": false}`。
冲突处理顺序：DataGate > freshness > approval/live guard > price/budget guard > skill-specific threshold。

# 降级规则

- When hard-required fields are missing, return missing_fields and confidence=low.
- When input is demo/sample/stale, return preview_only or dry_run and block formal approval/live.
- When source capability is read-only/manual, produce recommendation or task only.

# 输出结构

- confirmed outputs：dry_run_summary, live_allowed
- candidate outputs：execution_status, approval_gate

# forbidden_actions / 禁止事项

- treat_demo_data_as_real_today_data
- create_formal_approval_from_demo_or_stale_data
- bypass_data_gate_or_approval_guard
- recalculate_upstream_business_decision
- live_write_in_demo_mode
- execute_without_admin_or_owner_approval

# 测试样例

- 正常样例：见 `references/v20_behavior_cases.json` 的 normal/preview case。
- 缺字段样例：见 `references/v20_behavior_cases.json` 的 missing_hard_required case。
- demo/sample/stale 阻断样例：见 `references/v20_behavior_cases.json` 的 demo_preview case。
