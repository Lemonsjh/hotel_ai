## Design

在 `runtime.adapters.database` 的脱敏层加入 `PUBLIC_REVIEW_TEXT_FIELDS`。

脱敏规则：

1. 如果字段名是公开评论正文白名单，保留原文。
2. 如果字段名匹配敏感字段模式，继续脱敏。
3. 如果 profile 的 `privacy.redact_fields` 包含公开评论正文字段，白名单优先，仍保留原文。
4. 其他 profile 指定字段继续脱敏。

## Non-Goals

- 不做自然语言 PII 识别。
- 不改变 Feishu 输出预算和回复发布审批逻辑。
- 不暴露订单号、房号、客人姓名、内部操作人或 `product_cipher`。

## Verification

- 增加 `_redact_sensitive_fields()` 单元测试。
- 运行相关 database/deploy 测试。
- 运行 `openspec validate preserve-public-review-text --strict`。
