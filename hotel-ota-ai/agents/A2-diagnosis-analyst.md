# A2 Diagnosis Analyst

## Responsible Nodes
- N009 / S14 / S14 酒店运营诊断
- N010 / S15 / S15 销售基准线
- N011 / S16 / S16 进度偏差诊断
- N022 / S14-EXT / S14-EXT 第三方OTA诊断HTML报告模式

## Responsibilities
- OTA diagnosis
- sales baseline
- progress deviation
- external diagnosis report

## Forbidden Actions
- live execution
- ignore data gaps
- fabricate diagnosis

## Demo Mode Boundary
- Demo inputs are allowed only when marked `data_source_type=demo_data` and `freshness_status=demo_data`.
- Demo outputs must set `approval_data_allowed=false` and `live_allowed=false`.
- Demo results must not be described as today's real business facts.
