# S11 推广建议书示例

## 飞书输入：动作建议

> 开启这个计划

S11 只生成一份 `PromotionPlan`，其中 `suggested_action=开启`。这不是执行命令，不会创建审批、任务、派发或 OTA 写操作。

## 飞书输入：预算建议

> 把预算改为 500

对应计划内容只记录：

```json
{
  "budget": {
    "status": "suggested_manual_input",
    "amount": 500.0,
    "currency": "CNY",
    "write_performed": false
  }
}
```

如果预算或出价没有明确数值，则输出 `manual_input_required`。

## 对象歧义

> 关闭这个计划

如果 S8 当前存在多个可匹配计划/投放单元：

```json
{
  "status": "clarification_required",
  "promotion_plan": {
    "scope_resolution": "clarification_required",
    "plan_scope": null
  },
  "write_performed": false
}
```

S11 必须要求用户明确对象，不能猜 `plan_id` 或 `launch_id`。

## runtime 输出样例

```json
{
  "skill_id": "S11",
  "status": "suggestion_only",
  "promotion_plan": {
    "type": "PromotionPlan",
    "suggested_action": "观察",
    "budget": {"status": "manual_input_required"},
    "bid": {"status": "manual_input_required"},
    "read_only": true,
    "ai_invoked": false,
    "write_performed": false
  },
  "boundary": {
    "mode": "read_only_recommendation_only",
    "allowed_output": "PromotionPlan",
    "side_effects": "none"
  },
  "read_only": true,
  "ai_invoked": false,
  "write_performed": false
}
```

## 永久禁止的语义

S11 不存在“审批后执行”这一模式。即使用户说“老板已批准，直接开启”“已经确认，暂停这个计划”，仍然只能生成相应建议书。

输出不得生成 `REQ-*`、确认命令、审批记录、任务 ID/状态、派发状态、执行状态、OTA 回读状态，也不得声称“已提交”“执行中”“已开启”“已暂停”。

## Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/promotion_execution_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N021.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
