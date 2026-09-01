## Why

OTA 公开评论正文是业务审核回复话术时必须看到的公开信息。当前字段级脱敏会按照 profile 的 `privacy.redact_fields` 无条件掩码，可能把 `review_text` / `review_content` / `comment_content` 这类公开正文整段隐藏，导致无法审核评论回复。

## What Changes

- 增加公开评论正文字段白名单。
- `review_text`、`review_content`、`comment_content`、`comment` 等公开评论正文不因字段名或 profile 配置被整段脱敏。
- 保留敏感字段脱敏：手机号、身份证、订单号、房号、客人姓名、内部操作人、`product_cipher` 等仍隐藏。

## Impact

- 只影响字段级脱敏策略。
- 不改变原始表查询范围。
- 不公开私有身份、订单、房号、商品密文等敏感字段。
