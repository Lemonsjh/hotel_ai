## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

## V27 Collaboration Map Policy

Current runtime shape: one OpenClaw chief controller plus A0-A6 logical Agent layers. This repository does not yet run seven independent OpenClaw Agent instances. Any future true multi-Agent upgrade must add `runtime/agent_dispatcher.py`, Agent Message Contract, Agent State Store, Agent Handoff Record, Agent Failure Policy, and Agent Trace.

Drawio pages should support engineering collaboration, not only presentation. The current V27 drawing plan is:

| Page | Purpose | Must Show |
| --- | --- | --- |
| P1 Overview | End-to-end V27 map | N001-N022, E001-E067, SC01-SC10, A0-A6 logical handoff, demo/live boundary |
| P2 Data Sources And Field Mapping | Field governance | V27 fields, source aliases, candidate sources, field status, DataGate decision |
| P3 Agent Collaboration Main Chain | Logical Agent handoff | A0-A6 ownership, upstream/downstream nodes, forbidden handoff |
| P4 Skill Detail Chains | Skill development | S1-S17 + S14-EXT input/output, runtime command, failure fallback |
| P5 Exception And Fallback Chains | Safety behavior | missing_fields, data_gaps, stale/sample/demo/synthetic blocking, approval/live refusal |
| P6 Deployment And Runtime Chains | Operations | OpenClaw workspace, private config, SQLite demo DB, env-check, rollback path |

Every page should reference `contracts/v27/contract.json` as the machine-readable authority and should distinguish `missing_fields` from `data_gaps`.

# V20 Drawio Page Registry

Generated from the V20 drawio file. Use V19 JSON as the business source of truth when page labels differ.

| Page | Name | Diagram ID | Cells | Label sample |
| --- | --- | --- | --- | --- |
| 1 | P01 总地图 | v19_487402 | 63 | V19 总地图｜恢复 V9 边密度：只画业务主链路边，扩展依赖不进图<br>A区｜入口/权限/数据闸门<br>B区｜并行采集/感知/诊断输入 |
| 2 | P02 链路目录-主链路白名单 | v19_847631 | 47 | P02 链路拆分目录｜V19 主链路边白名单<br>场景<br>链路名称 |
| 3 | P03 SC01 主链路 | v19_363176 | 20 | P03 SC01｜今天经营怎么样 / 经营快报链路<br>入口与安全<br>采集/分析/决策 |
| 4 | P04 SC02 主链路 | v19_676985 | 32 | P04 SC02｜做一次 OTA 诊断 / 酒店运营诊断链路｜<br>入口与安全<br>采集/分析/决策 |
| 5 | P05 SC03 主链路 | v19_551902 | 45 | P05 SC03｜今天要不要调价 / 收益决策链路｜<br>入口与安全<br>采集/分析/决策 |
| 6 | P06 SC04 主链路 | v19_991257 | 26 | P06 SC04｜每小时进度巡检 / 偏差链路｜<br>入口与安全<br>采集/分析/决策 |
| 7 | P07 SC05 主链路 | v19_210984 | 26 | P07 SC05｜竞对降价怎么办 / 竞对预警链路｜<br>入口与安全<br>采集/分析/决策 |
| 8 | P08 SC06 主链路 | v19_949424 | 30 | P08 SC06｜要不要开活动 / 活动推广链路｜<br>入口与安全<br>采集/分析/决策 |
| 9 | P09 SC07 主链路 | v19_514460 | 25 | P09 SC07｜出现差评怎么处理 / 口碑回复链路｜<br>入口与安全<br>采集/分析/决策 |
| 10 | P10 SC08 主链路 | v19_926695 | 23 | P10 SC08｜客户订单分析 / 客群链路｜<br>入口与安全<br>采集/分析/决策 |
| 11 | P11 SC09 主链路 | v19_469614 | 17 | P11 SC09｜沉淀这次复盘 / 经验进化链路｜<br>入口与安全<br>采集/分析/决策 |
| 12 | P12 SC10 主链路 | v19_466269 | 20 | P12 SC10｜第三方酒店 OTA 诊断 / S14-EXT 链路｜<br>入口与安全<br>采集/分析/决策 |
| 13 | P13 字段治理支撑页 | v19_138123 | 7 | P14 字段治理支撑页｜不画业务连接，只说明字段关系<br>功能逻辑蓝图算法字段<br><br>先确定算法真正要什么字段。字段不是以当前代码为准。<br>PMS/OTA/外部可采集字段<br><br>再用整体架构分析里的实际来源字段做可采集性校验。 |
| 14 | p0p1 | R4hMNXk8XjCNlWVnYoVK | 39 | V19 总地图｜恢复 V9 边密度：只画业务主链路边，扩展依赖不进图<br>A区｜入口/权限/数据闸门<br>B区｜并行采集/感知/诊断输入 |
