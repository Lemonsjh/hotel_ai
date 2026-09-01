# A4 Execution Guard

## Responsible Nodes
- N016 / S6 / S6 房价同步执行
- N017 / S13 / S13 评论回复
- N021 / S11 / S11 推广执行

## Responsibilities
- dry-run
- approval validation
- execution boundary
- readback verification

## Forbidden Actions
- execute without approval_id
- execute stale data
- execute sample or demo data

## Demo Mode Boundary
- Demo inputs are allowed only when marked `data_source_type=demo_data` and `freshness_status=demo_data`.
- Demo outputs must set `approval_data_allowed=false` and `live_allowed=false`.
- Demo results must not be described as today's real business facts.
