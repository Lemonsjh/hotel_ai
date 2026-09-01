# S14 综合运营诊断示例

## 请求示例

主 S14 不接收 Excel、MySQL 表名或原始指标。请求必须包含服务端固定的身份和版本，以及上游能力已经生成的 versioned result。

```json
{
  "organization_id": "org-puyue",
  "hotel_id": "puyue",
  "target_business_date": "2026-08-03",
  "as_of_datetime": "2026-08-03T14:30:00+08:00",
  "contract_revision": "diagnosis-contract.v1",
  "policy_revision": "diagnosis-default.v1",
  "capability_results": [
    {
      "capability_id": "S2",
      "result_id": "s2-20260803-1430",
      "result_version": 1,
      "status": "ok",
      "organization_id": "org-puyue",
      "hotel_id": "puyue",
      "target_business_date": "2026-08-03",
      "as_of_datetime": "2026-08-03T14:30:00+08:00",
      "effective_window": {
        "type": "current_snapshot",
        "start": "2026-08-03T14:30:00+08:00",
        "end": "2026-08-03T14:30:00+08:00"
      },
      "captured_at": "2026-08-03T14:29:40+08:00",
      "source_grain": ["hotel", "canonical_room_type"],
      "source_units": {
        "committed_sold_rooms": "room",
        "committed_occupancy_rate": "pct"
      },
      "deterministic_payload": {
        "decision_axes": {
          "sales_progress": {
            "actual": 14,
            "unit": "room",
            "effective_window": "current_snapshot",
            "evidence_refs": ["sha256:s2-sales"]
          }
        },
        "diagnostic_items": []
      },
      "evidence_refs": ["sha256:s2-result"],
      "quality_flags": [],
      "contract_revision": "diagnosis-contract.v1",
      "policy_revision": "diagnosis-default.v1"
    }
  ],
  "handoffs": []
}
```

生产请求需要同时提供 S2、S4、S7、S8、S9、S10、S12、S15、S16、S17。示例只展示单个 result 的结构；缺少其余能力时，S14会生成对应 `missing_input` item，而不是用样例值补齐。

## 上游确定性 item 示例

```json
{
  "module_id": "operating_revenue",
  "issue_code": "sales_progress_lag",
  "issue_type": "anomaly",
  "severity": "medium",
  "status": "open",
  "confidence": 0.86,
  "impact": {
    "metric": "target_progress_delta_pp",
    "value": -9.4,
    "unit": "pp"
  },
  "evidence_refs": ["sha256:s16-progress"],
  "missing_inputs": [],
  "next_checks": ["check_room_type_structure"],
  "eligible_handoff": null,
  "forbidden_conclusions": ["do_not_attribute_to_price_or_traffic"]
}
```

S14会重新生成稳定 `item_id`，但不会修改严重度、数值和单位。

## 不同观察窗口

以下组合是合法的：

- S2：当前库存快照；
- S9：近30日流量转化；
- S10：近30日推广效果；
- S12：评价窗口；
- S15：固定 materialization；
- S16：当前 as-of 偏差。

S14只校验各自 `effective_window` 和 `captured_at` 合法，不要求所有结果拥有相同 `snapshot_time`。

## 缺少 S15 的传播示例

当 S15 缺失而 S16仍返回结果时：

1. S14生成 `missing_input:S15`；
2. S16的诊断 item 保留；
3. S16 item 增加 `blocked_by=<S15 missing item_id>`；
4. 主问题显示为基线缺口，不能改写成销售严重落后。

## handoff 示例

```json
{
  "capability_id": "S6",
  "handoff_ref": "result-ref:s6-price-candidate-01",
  "hotel_id": "puyue",
  "scope": {
    "room_type_id": "py03",
    "channel": "ctrip",
    "product_id": "product-123"
  },
  "target_business_date": "2026-08-03",
  "candidate_hash": "sha256:existing-candidate",
  "display_text": "查看已有价格候选"
}
```

S14只能显示该已有引用，不能创建价格任务、确认请求或OTA写操作。

## 旧入口结果

以下调用必须失败关闭：

```text
S14 Excel direct source
S14 MySQL operation_diagnosis payload
database-query --template operation_diagnosis
```

返回：

```json
{
  "status": "data_gap",
  "blocked_reason": "s14_direct_source_removed_use_versioned_capability_results"
}
```
