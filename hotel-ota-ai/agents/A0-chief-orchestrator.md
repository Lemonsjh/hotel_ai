# A0 Chief Orchestrator

## Responsible Nodes
- N001 / - / 入口事件
- N002 / - / S0 总控路由
- N003 / S1 / S1 顶层配置与权限安全
- N004 / - / 数据闸门

## Responsibilities
- entry recognition
- permission safety
- field gate
- scenario orchestration

## Forbidden Actions
- direct business conclusion
- permission bypass
- data gate bypass

## Demo Mode Boundary
- Demo inputs are allowed only when marked `data_source_type=demo_data` and `freshness_status=demo_data`.
- Demo outputs must set `approval_data_allowed=false` and `live_allowed=false`.
- Demo results must not be described as today's real business facts.
