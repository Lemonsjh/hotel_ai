# S14 综合运营诊断 runtime 命令

## 正式自动入口

正式执行不再要求调用方手工准备 bundle。runtime 会自动：

```text
查询已保存的 versioned capability result
→ 缺失时运行对应 capability
→ 包装并保存新版本
→ 组装 S2/S4/S7/S8/S9/S10/S12/S15/S16/S17 bundle
→ 执行 S14 编排
→ 保存 S14 诊断结果
```

推荐命令：

```bash
python runtime/hotel_ota_runtime.py s14-diagnosis \
  --hotel-id puyue \
  --date 2026-08-03 \
  --as-of-datetime 2026-08-03T15:30:00+08:00
```

如果 `hotels.org_id` 未配置，必须显式提供：

```bash
python runtime/hotel_ota_runtime.py s14-diagnosis \
  --organization-id org-puyue \
  --hotel-id puyue \
  --date 2026-08-03 \
  --as-of-datetime 2026-08-03T15:30:00+08:00
```

强制重新运行全部上游能力并产生新版本：

```bash
python runtime/hotel_ota_runtime.py s14-diagnosis \
  --organization-id org-puyue \
  --hotel-id puyue \
  --date 2026-08-03 \
  --refresh
```

默认合同：

```text
contract_revision=diagnosis-contract.v1
policy_revision=diagnosis-default.v1
```

## 低层 bundle 调试入口

已经有可信 bundle 时，仍可直接验证消费端：

```bash
python -m runtime.s14_capability_cli \
  --request-file /secure/runtime-input/s14-request.json \
  --assert-hotel-id puyue \
  --pretty
```

这个入口不会自动运行上游能力，主要用于合同验证和回放。

## 结果存储

SQLite 会自动创建：

```text
capability_results
s14_diagnosis_runs
```

查找已保存结果必须同时满足：

```text
organization_id 一致
hotel_id 一致
target_business_date 一致
captured_at <= as_of_datetime
contract_revision 兼容
policy_revision 兼容
```

已有兼容结果默认复用；`--refresh` 才会生成下一版本。

## 数据源规则

- S14只消费 S2/S4/S7/S8/S9/S10/S12/S15/S16/S17 的 versioned result。
- 各能力可以有不同的自然观察窗口。
- 某个能力失败或缺失时，保存其 `data_gap|conflict|stale|blocked` 状态并局部降级。
- S14不得使用 `operation_diagnosis` 聚合表重新计算经营指标。
- demo/sample/synthetic/hardcoded 结果不得进入正式 S14。
- 不得跨酒店、跨日期、跨平台或跨旧合同补齐。

## 已废止入口

以下参数不再可用：

```text
--source-mode excel
--source-mode mysql
--excel-path
```

以下直接数据源仍然失败关闭：

```text
database-query --template operation_diagnosis
diagnose_s14_excel_file
diagnose_s14_mysql_template_result
```

统一阻断码：

```text
s14_direct_source_removed_use_versioned_capability_results
```

## 写操作边界

S14始终：

```text
write_performed=false
direct_execution_allowed=false
approval_requested=false
live_allowed=false
```

S5/S6/S8/S13 handoff 必须已经存在，S14只返回 opaque result ref。
