# Feishu Auth Guard

## Purpose

This skill is an explicit Feishu authorization preflight and diagnostic tool for workflows that are not already entering through the production `feishu-route` gate.

The primary Feishu authorization path remains the existing runtime flow:

`feishu-route -> build_auth_context -> tenant_scope_gate -> permission_gate`

生产 Feishu 业务必须先具备可信会话和发送人身份。优先使用 `feishu-route --production-feishu` 让 runtime 完成鉴权；如果外层 Agent 没有直接进入 `feishu-route`，必须先运行本 guard 或 runtime `auth-check`，再决定是否调用业务 skill。

When `feishu-route` has already produced an authorized context, do not double-run this guard. Otherwise, run it before any natural-language Feishu business workflow that would read hotel data, diagnose, price, configure roles, or trigger approvals.

## When to run

Use this guard for:

- checking whether a Feishu sender and conversation can enter a hotel workflow;
- resolving `resolved_hotel_id` and `user_role` before an ambiguous natural-language workflow;
- diagnosing why a chat, sender, or hotel is blocked;
- validating new Feishu bindings or role-map changes;
- testing authorization without triggering downstream business logic.

Use the existing `feishu-route` authorization result when a snapshot, baseline, diagnosis, pricing, promotion, or review workflow already passed through it. If the workflow was started outside `feishu-route`, this guard is mandatory before downstream business logic.

## Runtime entrypoint

Use the Python module:

`runtime.safety.feishu_auth_guard`

Required runtime context:

- Feishu conversation id, normally `oc_*`
- Feishu sender identity, one of open id, user id, or union id
- Runtime SQLite database path
- Private role-map config path
- Requested action, such as `view_diagnosis` or `price_update`
- Optional requested hotel id

## Output contract

Allowed result:

```json
{
  "status": "ok",
  "guard": "feishu_auth_guard",
  "should_continue": true,
  "resolved_hotel_id": "puyue-demo",
  "user_role": "operator"
}
```

Blocked result:

```json
{
  "status": "blocked",
  "guard": "feishu_auth_guard",
  "should_continue": false,
  "fail_closed": true,
  "reason": "chat_not_bound_to_hotel",
  "safe_user_message": "当前飞书会话尚未绑定酒店。"
}
```

## Agent rule

If this guard is used and `should_continue` is not `true`, stop the current preflighted workflow and return `safe_user_message`. Do not call downstream business skills for that same workflow.

If `should_continue` is `true`, pass `resolved_hotel_id`, `user_role`, `auth_backend`, and `tenant_status` to downstream skills.

Missing trusted context is not the same as an unbound chat. If runtime returns `missing_required_feishu_auth_context` or `missing_trusted_business_chat_id`, say that the message lacks trusted Feishu context and cannot determine the binding; 不得把缺少可信上下文误报为群未绑定. Only say `chat_not_bound_to_hotel` when runtime actually received the real chat id and returned that binding result.

## Boundary

This skill only provides an explicit authorization preflight and diagnostic result. It must not perform pricing, diagnosis, promotion, or review business logic.
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 飞书鉴权守卫 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py auth-check --hotel-id <hotel_id>
```

Allowed runtime commands: `auth-check`, `role-map-preview`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

### 数据来源要求
runtime CLI and controlled database-query only.

### 生产环境禁止事项和 data_gap 规则

- 生产 Feishu 必须使用 verified role；需要时由 HOTEL_OTA_REQUIRE_VERIFIED_ROLE 强制
- 生产 Feishu 业务必须携带可信会话和发送人身份；缺少时返回 `missing_required_feishu_auth_context` / `missing_trusted_business_chat_id`，不得把缺少可信上下文误报为群未绑定
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

- User says "查身份": route to `feishu_auth_guard` and run `auth-check`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
