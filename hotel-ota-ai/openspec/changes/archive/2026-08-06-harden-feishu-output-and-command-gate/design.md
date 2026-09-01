## Context

renderer 已维护 internal field 列表，但 context 仍包含内部值，且最终发送前未调用 `feishu_output_gate`。模板出现 coverage、小时曲线、model/provider 和本地调试参数。

## Goals / Non-Goals

**Goals:** 最终文本总是经过安全闸门；普通用户仅看业务摘要；维护请求明确拒绝。

**Non-Goals:** 不删除本地 developer debug 能力，不删除 runtime 完整结果，不改变业务节点输入输出。

## Decisions

- `build_feishu_send_payload` 生成文本后执行 gate；插件发送前重复 gate，阻断时替换为安全模板。
- 普通渲染上下文采用公开字段白名单；coverage、trace、hourly arrays、身份、路径、model/provider 仅在本地 debug 可见。
- 所有非 debug 模板通过静态禁词测试；截断提示不暴露 CLI 参数。

## Risks / Trade-offs

- 误判会阻断正常文本 → 保留 correlation id 与本地 debug 日志，不向飞书泄漏规则细节。
- 文本变短会减少诊断细节 → 业务用户保留结论、数据标签、风险和下一步。
