## Context

运行清单已指定 V27，但部分规则 metadata 和 loader 仍走旧顶层路径。当前请求时间过滤是正确的，测试却固定断言至少八个小时点。市场事件和热度缺口未完全降低整体状态。

## Goals / Non-Goals

**Goals:** 活动 runtime 引用只指向 V27；缺外部市场字段如实 partial；经验候选不可沉淀敏感值；时间测试不依赖机器时钟。

**Non-Goals:** 不替换 V27 canonical JSON、不接入真实市场 provider、不修改需求指数权重。

## Decisions

- 中性 loader 和 active rule metadata 引用 `contracts/v27/`；仅名称显式带 `v26` 的资产可保留 legacy 引用。
- market overall status 合并 weather、events、regional heat、运营和进度质量；任一 required market source 缺失必须反映 partial/data_gap。
- experience candidate 对可写字段白名单化，并对 DSN、token、open/chat identity、电话等值模式拒绝或脱敏。
- 时间测试注入固定 `as_of_time`，并断言返回点不晚于该时间。

## Risks / Trade-offs

- V27 路径收敛可能暴露旧 fixture 依赖 → 先加 drift 测试并保留显式 legacy asset。
- 更严格市场状态会减少 downstream 可用性 → 这是避免错误经营结论的预期行为。
