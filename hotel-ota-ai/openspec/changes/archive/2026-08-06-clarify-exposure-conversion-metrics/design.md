## Context

当前 `runtime/adapters/database.py` 使用 `_first_metric_value(metric_rows, "exposure", "impression", "曝光")` 提取曝光，无法区分 `曝光量` 和 `曝光人数`。

## Goals / Non-Goals

**Goals:** 曝光数值有单位；优先次数口径；转化率有明确 basis。

**Non-Goals:** 不重算所有历史转化漏斗；不新增数据库字段；不硬编码同行平均。

## Decisions

- 先精确匹配 `曝光量`、`exposure`、`impression`、`impressions` 作为次数口径。
- 未命中时匹配 `曝光人数`、`exposure_users`、`impression_users` 作为人数口径。
- `payment_conversion_rate` 默认为 `view_to_payment`；如果源指标名包含 `曝光`，标记为 `exposure_to_payment`。

## Risks / Trade-offs

- 源表如果只有中文模糊指标名，仍依赖 `metric_name` 文本；因此输出 `exposure_metric_name` 便于人工复核。
