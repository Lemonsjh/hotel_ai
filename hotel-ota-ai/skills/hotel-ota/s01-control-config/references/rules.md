# S1 总控配置 规则

## 核心输入字段
- `hotel_id`
- `hotel_name`
- `room_types`
- `strategy_mode`
- `price_floor_by_room_type`
- `approval_policy`
- `roles`

## 判断逻辑
1. 校验酒店配置是否完整
2. 确认价格底线、角色权限和审批链路
3. 将缺失字段标记为 manual_required，不阻塞 dry-run

## 角色权限判断
- `admin` 可管理飞书角色表、安全配置、skill 开关和紧急停用。
- `owner` 可查看配置、调整业务阈值、审批真实执行，并可在当前绑定酒店内通过 ROLE 流程管理其他 `owner/operator/frontdesk`，包括直接进行 `owner/operator/frontdesk` 之间的角色替换；不得修改自己、不得修改 `admin`、不得跨酒店操作。owner 发起的 ROLE 请求可由该 owner 自己确认。
- `operator` 可查看业务配置和发起配置缺失追问，不可调整安全阈值。
- `frontdesk` 只能查看与自己任务相关的执行说明。
- `guest` 不返回酒店配置细节，只提示联系 admin 加入角色表。

## 可配置参数
- 蓝图中未最终确认的阈值标记为 `configurable`。
- 多源资料冲突时输出 `needs_business_confirm`，并采用更保守建议。
- API 未确认时字段质量为 `manual_required` 或 `inferred`。

## 异常处理
- 缺关键字段时先追问或降级为 sample/manual/RPA，不让 skill 失败退出。
- 低质量字段只能用于诊断、提示和 dry-run，不得用于真实执行。
- 原始 API 状态码必须先由 runtime 转成统一枚举后再解释。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- 必须记录请求摘要、响应码、失败原因和人工处理建议。

## V27 可施工算法规格

# 算法来源

- 对应节点：N003 / S1 顶层配置与权限安全
- 对应 Agent：A0
- 对应 BP：P0
- 对应源文件：`references/source/source_manifest.yaml`
- 对应字段契约：`contracts/node_io_contract.yaml`
- 对应 runtime algorithm_rules：`runtime/algorithm_rules/auth_policy.yaml`

# 输入字段

## hard_required
缺失则阻断：auth_context, role, action

## soft_required
缺失可继续但必须输出 data_gap：open_id, approval_id, live_switch

## optional
增强判断，不阻断主链路：none

## candidate
候选字段，不稳定，不用于 live：none

## blocked_for_live
可用于诊断或 dry-run，不得用于正式执行：demo_data, sample_data, stale, missing_date

# 算法步骤

1. Normalize Feishu ou_* as open_id unless an explicit user_id is supplied.
2. Resolve role only from /etc/hotel-ota-ai/feishu-role-map.json or verified runtime auth_context.
3. Map action to required permission and deny missing_identity/guest for business skills.
4. Emit auth_context and permission_gate; never infer admin/owner from chat memory.

# 判断规则

阈值与分级来自 `runtime/algorithm_rules/auth_policy.yaml`：`{"guest_business_skill_allowed": false, "frontdesk_revenue_allowed": false, "operator_live_allowed": false}`。
冲突处理顺序：DataGate > freshness > approval/live guard > price/budget guard > skill-specific threshold。

# 降级规则

- When hard-required fields are missing, return missing_fields and confidence=low.
- When input is demo/sample/stale, return preview_only or dry_run and block formal approval/live.
- When source capability is read-only/manual, produce recommendation or task only.

# 输出结构

- confirmed outputs：auth_context, approval_data_allowed, live_allowed
- candidate outputs：none

# forbidden_actions / 禁止事项

- treat_demo_data_as_real_today_data
- create_formal_approval_from_demo_or_stale_data
- bypass_data_gate_or_approval_guard

# 测试样例

- 正常样例：见 `references/v20_behavior_cases.json` 的 normal/preview case。
- 缺字段样例：见 `references/v20_behavior_cases.json` 的 missing_hard_required case。
- demo/sample/stale 阻断样例：见 `references/v20_behavior_cases.json` 的 demo_preview case。
