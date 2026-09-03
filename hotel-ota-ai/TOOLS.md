# OpenClaw 工具调用规则

本文件说明本地开发和运行验证时应该优先调用哪些 runtime 命令。它不是权限来源、业务数据来源或审批依据。

## 1. 总原则

稳定、可验证、容易出错的输入输出逻辑优先交给 `runtime/hotel_ota_runtime.py`。OpenClaw skill 和模型负责中文业务解释、缺失信息追问、飞书回复、策略取舍和审批沟通。

生产飞书业务必须以 runtime 返回结果为准，不能从提示词、历史记忆或用户自称生成业务结论。

当前机器可读契约事实源是 `contracts/v27/contract.json`；运行命令、数据库映射和飞书输出若与契约冲突，必须以 runtime 校验和 V27 契约为准。

## 2. Runtime 优先场景

以下情况先调用 runtime，再组织中文回复：

- 环境自检：`env-check`
- 飞书路由和渲染：`feishu-route`
- 飞书最终输出检查：`feishu-output-gate`
- 经营快照：`snapshot`
- 销售基准线：`baseline`
- 进度偏差：`deviation`
- 收益决策：`revenue-decision`
- 需求指数：`demand-index`
- OTA 健康：`ota-health`
- 流量转化：`conversion-diagnosis`
- 竞对预警：`competition-alert`
- 前台任务：`frontdesk-tasks`
- 客户订单聚合分析：`customer-analysis`
- 口碑诊断：`reputation-diagnosis`
- 推广策略/ROI/执行预览：`promotion-plan`、`promotion-roi`、`promotion-execute`
- 调价预览和任务写入：`execute-price`
- 数据库只读来源：`database-inspect`、`database-query`
- API 样例归一化：`normalize-sample`

## 3. 生产酒店本地验证示例

生产试运行酒店 ID 必须来自私有配置或 tenant registry，不得使用根文件硬编码：

```bash
python runtime/hotel_ota_runtime.py env-check
python runtime/hotel_ota_runtime.py snapshot --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py baseline --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py deviation --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py revenue-decision --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py demand-index --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py ota-health --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py competition-alert --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py frontdesk-tasks --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py customer-analysis --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py reputation-diagnosis --hotel-id <hotel_id>
```

如果真实数据源缺失，生产链路应返回 `data_gap`、`schema_drift`、`stale` 或 `missing_date`，不得自动使用 demo/sample/synthetic 数据生成正式业务结果。

## 4. 数据库只读来源

```bash
python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode connection
python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode tables
python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template operating_snapshot --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template price_snapshot --hotel-id <hotel_id>
python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template order_snapshot --hotel-id <hotel_id>
```

数据库来源必须通过私有 mapping profile 配置。不要在飞书、日志或文档中输出 DSN、用户名、密码、token、私有路径或原始 SQL 结果。

`database-inspect --mode tables` 必须作为生产试运行前的只读事实检查，输出每张表的 `has_hotel_id`、`has_hotel_name`、`has_room_type_id`、`has_room_type_name`、`has_source_platform`、`has_source_room_type_id`、`has_source_product_id`、`has_business_date`、`latest_business_date`、`row_count_estimate` 和 `data_status`。`hotel_name_legacy`、`room_type_mapping_pending`、`source_product_mapping_requires_room_type` 只能作为风险标记，不能自动放行正式调价。

当前 `hotel_puyue` MySQL mapping 是 27 表模板，包含 `hotel_room_type_mapping`、PMS 经营表、OTA 指标/价格/活动/点评表、`meituan_ota_nearby_event` 和价格任务 outbox。`meituan_ota_nearby_event` 可作为周边活动上下文，但不得单独触发 S5 调价或 S6 任务。历史 PMS 表如果 `hotel_id` 为空，可通过 `hotel_room_type_mapping` 中相同 `hotel_name` 受控反推出酒店范围；平台字段为空时按散客 `walkin` 处理。

兼容查询层命令仍走 `database-query`，内部由 `runtime/adapters/normalized_query.py` 统一字段：

```bash
python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template ota_price_mapping --hotel-id <hotel_id>
```

输出出现 `mapping_pending` 时，只能 preview/诊断（读路径可暴露名称反推的 `room_type_id`，标 `inferred_by_name` 低置信）；S5/S6 写 price task 只接受 active `mapping_status=AUTO`，`CONFIRMED`、其他状态和 `match_rule` 均不能放行。仍必须存在精确 `room_type_id`、`source_product_id`，名称反推不得写入；携程还必须具备内部 `product_cipher`。

## 5. S14-EXT 注册报告

注册 Excel 源通过私有 `s14-source.json` 管理，飞书只传 `source_key`：

```bash
export HOTEL_OTA_S14_REPORT_DIR=/var/lib/hotel-ota-ai/s14/reports
export HOTEL_OTA_S14_REPORT_BASE_URL=https://<your-domain>/reports
python runtime/hotel_ota_runtime.py feishu-route --message "s14 source=monthly_excel" --production-feishu ...
```

不要在飞书正文中传服务器路径。未配置 `HOTEL_OTA_S14_REPORT_BASE_URL` 时只生成本地 HTML，不输出可跳转链接。S14-EXT 结果只用于 preview，不创建审批、不 live。

## 6. 本地 demo 命令

这些命令只用于本地演示或测试环境，不是生产飞书路径：

```bash
python runtime/hotel_ota_runtime.py seed-demo
python runtime/hotel_ota_runtime.py generate-today-demo --write-db
python runtime/hotel_ota_runtime.py --demo demo-chain --all
python runtime/hotel_ota_runtime.py --demo demo-node --all
python runtime/hotel_ota_runtime.py --demo demo-chain --scenario SC01
python runtime/hotel_ota_runtime.py --demo demo-node --node N022
```

Demo 命令只允许 `dry_run`、`preview_only`、`simulation_only` 和 `html_report_preview`。任何 demo/sample/stale/missing_date payload 都不得创建正式审批，不得进入 live 执行。

## 7. 调价任务验证

旧直连 API live 开关不作为生产调价路径。S6 只能在审查确认、护栏校验和数据新鲜度通过后写入价格任务，再由独立插件处理并回查。

**按商品精确调价（重要）**：同一房型下常有多个 OTA 商品，价格差异巨大（挂牌全日房 / 超级团购 / 钟点房）。调价必须用 `--ota-product-id` 指定要改的那个商品；**不指定且该房型有多个商品时，会被 `blocked: price_task_requires_ota_product_id` 拒绝并返回候选商品清单**，防止把挂牌价灌给团购商品（如挂牌 ¥356→¥360 时把团购 ¥99 也写成 ¥360）。护栏按该商品的真实当前价校验。

示例：

```bash
python runtime/hotel_ota_runtime.py execute-price \
  --hotel-id <hotel_id> \
  --hotel-name '<hotel_name>' \
  --room-type-id <统一房型ID> \
  --room-type-name '<房型名>' \
  --channel-source meituan \
  --ota-product-id <要调价的OTA商品ID> \
  --normal-price 360 \
  --business-date 2026-06-30 \
  --begin-date 2026-06-30 \
  --end-date 2026-06-30 \
  --user-role admin \
  --approval-id APPROVAL-ID-FOR-TEST
```

`execute_status=PENDING/SUCCESS/FAILED` 是插件兼容状态。完整任务闭环还必须区分 `review_status`、`plugin_status` 和 `verification_status`。

**查调价历史**（哪些价调过、结果如何）：

```bash
python runtime/hotel_ota_runtime.py price-task-history \
  --channel-source meituan --hotel-name '<hotel_name>'
# 可选过滤:--business-date、--source-decision-id
```

返回每条调价任务的 `target_sale_price`、`execute_status`、`created_by`、`created_at`、`executed_at`、`error_message` 及按状态计数。调价历史即调价任务表本身，无需另建记录。

## 8. Sales Baseline 验证

```bash
python runtime/hotel_ota_runtime.py baseline --hotel-id <hotel_id>
```

S15 会输出 `hourly_target_curve`。小时曲线只来自可复现的真实历史分时批次；缺失小时保留缺口并标记采集覆盖不足，不使用最近值、默认累计比例或默认锚点补造生产事实。`hourly_curve_source`、`hourly_curve_evidence` 和 `baseline_confidence` 必须如实反映覆盖情况。

## 9. Market Source 配置

真实 weather/events/regional heat 配置只能放在服务器私有配置中：

```bash
cp config/market-source.example.json /etc/hotel-ota-ai/market-source.json
chmod 600 /etc/hotel-ota-ai/market-source.json
export HOTEL_OTA_MARKET_SOURCE_CONFIG=/etc/hotel-ota-ai/market-source.json
```

事件桥关闭或 token 缺失时，S4 可返回 `partial` / `data_gap`，可以用 `meituan_ota_nearby_event` 表作为周边活动上下文。

## 10. 飞书淡旺季人工标签

`calendar_days.season_tag` 是单值字段，一个日期只能有一个标签。系统默认值统一由 `runtime/decisions/calendar.py::build_calendar_days()` 计算，包括 `holiday_peak`、`holiday_warmup`、`holiday_cooldown`、`summer_vacation`、`winter_vacation`、`normal`；不得在飞书路由或恢复逻辑中另写一套默认值。

飞书人工配置仅接受 `淡季`、`平季`、`旺季`，由已授权的 `owner/admin` 在绑定群内设置。设置是覆盖式写入，不是追加标签；后续日历同步保留仍存在的人工中文标签。

查询人工标签必须走 runtime-backed 日历路径。例如「2026年哪些天是旺季」「什么时候是旺季」应读取 `calendar_days` 中实际保存的人工标签日期，不得误路由到 `menu`，也不得把系统 `summer_vacation` 自动解释成人工「旺季」。

撤销人工覆盖使用明确日期或月份，例如：

```text
将2026-08-07和2026-08-09恢复为系统默认
将2026年8月恢复为系统默认
```

恢复时只把明确选中的日期的 `season_tag` 改回 `build_calendar_days()` 对应日期计算出的系统默认值，不重写活动热度等其他日历字段。`至/到` 表示连续日期区间；`和/、/与/及` 表示离散日期列表，不能把中间未选日期一起修改。

「将这俩天改回原来的标签」这类只有上下文代词、没有明确日期的消息可以被识别为恢复意图，但 deterministic runtime 不得猜日期，必须返回 `calendar_season_exact_date_required`。上层对话能力如果能从当前会话可靠解析出具体日期，应重新以明确日期调用 runtime；不得退回 `menu` 或假装恢复成功。

## 11. 禁止事项

- 不得在未审查确认情况下执行真实调价。
- 不得把未授权飞书用户当作 operator/admin。
- 不得用旧 live API 开关作为当前调价路径。
- 不得记录或回复真实密钥、签名、token、验证码。
- 不得让模型直接生成或执行自由 SQL。
- 不得在日志、飞书或 skill 中输出 DSN、用户名、密码、私有路径。
- 旧数据、demo/sample 数据只输出演示建议，不创建正式审批。
- 生产飞书不得展示行级订单明细、原始表结构、完整 runtime JSON、模型/provider footer 或源码修改声明。

## 12. 输出 profile

- `developer_debug`：展示脱敏 runtime metadata、节点、skill、场景和调试字段。
- `owner_business`：展示结论、指标、风险、建议和执行状态。
- `operator_workbench`：展示操作清单、dry-run、阻断原因和下一步。
- `frontdesk_task`：只展示前台任务。
- `guest_limited`：只展示无权限提示。
