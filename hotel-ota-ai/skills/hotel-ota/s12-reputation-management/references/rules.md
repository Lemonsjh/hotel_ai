# S12 口碑管理 规则

## 核心输入字段
- `rating_total`
- `bad_review_rate`
- `review_content`
- `guest_impression_keywords`
- `bad_review_followup_status`

## 判断逻辑
1. 先做评论分类、差评升级、问题回流
2. 严重问题进入店长升级和门店整改
3. 口碑问题回流 S14 和 S3

## 可配置参数
- 蓝图中未最终确认的阈值标记为 `configurable`。
- 多源资料冲突时输出 `needs_business_confirm`，并采用更保守建议。
- API 未确认时字段质量为 `manual_required` 或 `inferred`。

## 异常处理
- 缺关键字段时先追问或降级为 sample/manual/RPA，不让 skill 失败退出。
- 低质量字段只能用于诊断、提示和 dry-run，不得用于真实执行。
- 原始 API 状态码必须先由 runtime 转成统一枚举后再解释。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- 必须记录请求摘要、响应码、失败原因和人工处理建议。


## V27 可施工算法规格

字段与 IO 以 `contracts/v27/` 为准；demo_data 仅可 preview/dry-run，不能正式审批或 live。
