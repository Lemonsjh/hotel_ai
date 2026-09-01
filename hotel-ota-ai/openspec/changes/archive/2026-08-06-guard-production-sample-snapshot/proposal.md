## Why

生产飞书路径必须以真实经营数据或明确 `data_gap` 为准，不能把本地 demo/sample 的硬编码业务数字当成生产证据。

当前 `sample_snapshot()` 中保留了 `170`、`107`、`5.74`、`58`、`4` 等演示数字，且部分决策模块仍直接 import/use 该函数。即使生产入口已有 demo fallback gate，也需要在业务决策层增加 fail-closed 约束，防止生产 Feishu 路径绕过入口保护后泄漏样例数字。

## What Changes

- 将 `sample_snapshot()` 明确限定为 demo/local fixture。
- 增加生产 guard：`production_feishu=True` 或等价生产上下文缺少真实业务数据时，返回 `data_gap` / `None` 字段，不返回硬编码数字。
- 覆盖 demand / pricing / deviation / ota_health 中直接调用 sample snapshot 的路径。
- 增加回归测试，验证生产路径输出不包含 `170`、`107`、`5.74`、`58`、`sample_data`、`demo_data` 作为业务证据。

## Impact

- 生产 Feishu 中缺真实数据时输出会更保守，改为明确数据缺口。
- 本地 demo/test fixture 能力保留，但必须通过显式 demo/local 路径使用。
- 不改变数据库 schema，不执行生产写入。
