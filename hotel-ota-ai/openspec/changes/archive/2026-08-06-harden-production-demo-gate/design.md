## Context

生产入口通过 `safe_route_feishu_command(..., production_feishu=True)` 进入鉴权与租户边界。历史风险是模型或路由在显式 demo 请求、demo hotel id 或缺少真实酒店上下文时静默回退到 demo 数据。

## Goals / Non-Goals

**Goals:** 生产飞书显式 demo 必须 blocked；`*-demo` hotel id 必须 blocked；缺真实数据不能 fallback 到 demo/sample/synthetic/static fixture。

**Non-Goals:** 不删除本地 CLI demo；不修改测试环境演示数据生成；不改变本地 `route_feishu_command` 的 demo 预览能力。

## Decisions

- `production_feishu=True` 的显式 demo 请求返回 `blocked_reason=demo_not_allowed_in_production_feishu`。
- `production_feishu=True` 的 demo hotel id 请求返回 `blocked_reason=demo_hotel_not_allowed_in_production_feishu`。
- 非显式 demo 的 demo fallback intent 在生产飞书返回 `production_feishu_no_demo_fallback` / `data_gap`，不产出演示业务结论。

## Risks / Trade-offs

- 生产飞书里无法用“演示一下”快速解释功能；需要提示用户切到本地 CLI 或测试环境运行演示。
- 非生产路径仍保留 demo 能力，必须继续由测试覆盖避免误删。
