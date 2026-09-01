---
name: s13-review-reply
description: "S13 评论智能回复：基于 S12 签发的 opaque review ref 生成、编辑、确认和追踪评论回复任务。"
---

# S13 评论智能回复

## 权威边界

本 skill 以当前 S1–S17 字段与算法 MD 中的 S13 为唯一业务标准。S13 的机器合同为 `contracts/s13_review_reply_contract.json`，运行架构为 `architecture/s13_review_reply_runtime.json`。V27、OpenClaw、N017/A4 和旧 guest 语义不再控制 S13。

执行前读取：

- `references/input_schema.json`
- `references/output_schema.json`
- `references/rules.md`
- `references/examples.md`
- `references/runtime_commands.md`

已实现代码：

- `runtime/s12_review_refs.py`
- `runtime/s13/repository.py`
- `runtime/s13/source.py`
- `runtime/s13/task_outbox.py`
- `runtime/s13/policy.py`
- `runtime/s13/service.py`
- `runtime/s13/cli.py`
- `runtime/s13/feishu.py`
- `runtime/s13_runtime_patch.py`

## 产品入口

S13 提供三个入口：

1. `待回复评论`
2. `生成回复`
3. `回复任务状态`

admin/owner/operator 可以选择评论、填写人工回复或请求候选草稿、编辑草稿并通过确定性文本命令确认提交。viewer/frontdesk/guest 没有评论回复任务权限，不能通过其他全局权限绕过 S13 的确定性风险检查、确认和任务写入规则。

## 输入合同

业务输入只能使用 S12 在当前 `RequestContext.hotel_id` 下签发的 opaque `review_ref`。visible token 不编码酒店、平台、物理 review ID、正文或 source snapshot。服务端必须由该 ref 解析并重新校验：

- exact `hotel_id`
- 平台 scope
- 物理 `review_id`
- 最新 source snapshot
- 内容 digest
- 星级、正文及 `is_replied`

消息正文不得直接提供或覆盖酒店、平台、物理 review ID、原始评论身份或 source snapshot。原始酒店/POI 标识、图片 URL、客人、订单和房号不得进入候选生成、飞书消息或任务审计正文。第一版不读取评论图片正文。

## 资格判定

生成草稿前必须同时满足：

- review 仍属于当前 exact 酒店和平台；
- `is_replied=0`；
- `review_ref` 未过期；
- source snapshot 和内容 digest 未变化；
- 当前角色和权限有效；
- 同一 review 不存在 active `pending/processing` 任务。

已有 `success` 任务返回 `already_handled`。`failed/cancelled` 只能经过新草稿、新确认和受控 CAS 重试。

安全、隐私、歧视、威胁、伤害、法律争议、索赔或重大舆情命中确定性规则时，状态进入 `blocked_escalation`；不得自动形成可提交草稿，也不得生成自动补偿或私信建议。

## 纯评分评论

`review_content` 允许为 `NULL`。纯评分评论不得被拒绝或伪造正文，应根据星级和已批准语气生成确定性通用草稿。允许为空的是源评论正文，不是最终 `reply_content`；人工回复必须为 1–2000 字符。

## 清洗与候选生成

非空正文进入草稿流程前，先去除 URL、电话、邮箱、身份证/订单号、房号、联系方式、疑似姓名和重复空白，再运行主题和风险规则。

普通非空评论最多调用一次批准的内容生成能力；当前 runtime 在模型不可用或未配置时使用确定性模板，并保留人工填写回复入口。候选固定包含：

```json
{
  "draft": "string, 最大 2000 字符",
  "tone": "neutral|professional|warm|apologetic",
  "acknowledged_topics": ["approved_topic"],
  "risk_flags": ["approved_flag"],
  "requires_human_escalation": false
}
```

生成后必须检查长度、PII、禁用承诺、虚构事实和主题白名单。禁止承诺退款、赔偿、升级房型、处罚员工、删除评论、线下联系、已修复或已经公开回复，除非事实来自当前已批准的结构化输入。候选生成不得改变风险等级、审批、任务状态或执行写入。

## 版本、预览与确认

状态机固定为：

```text
eligible -> selected -> deterministic_risk_check
         -> blocked_escalation
         |  draft_requested -> ai_candidate|deterministic_candidate|human_draft
         -> human_edited -> confirmation_pending
         -> confirmed|rejected|cancelled|expired|invalidated_by_new_version
         -> fixed_task_dml -> exact_pending_readback -> provider_status_observed
```

每次重生或人工编辑都生成新的 `draft_version`、`content_hash` 和 `REQ-*`，旧确认立即失效，不得原地覆盖。

提交、拒绝、取消、查询和重试使用：

```text
确认 REQ-*
拒绝 REQ-*
取消 REQ-*
查询 REQ-*
重试 REQ-*
```

用户只提交 `REQ-*`，不提交 `draft_version` 或 `content_hash`。服务端从 sealed request 读取 expected version/hash，并与当前最新草稿重新比对。不使用按钮、callback 或原卡更新。

确认时重新检查用户、角色、酒店、review 当前状态、sealed version/hash、request expiry、环境 write gate、writer grants、平台范围和自批规则。重复投递相同确认命令必须幂等回放，不得再次 INSERT。

## 写任务范围

当前批准的 task sink 仅为美团评论：

- `platform=meituan`
- `channel_source=meituan`

大众点评、携程、去哪儿、同程和智行只能生成、编辑和复制草稿；未获得新的书面批准前不得写入 `ota_review_reply_task`。

## 固定 DML 与 readback

首次提交仅允许对 `ota_review_reply_task` 执行固定参数化 INSERT，列固定为：

`hotel_id, platform, channel_source, review_id, review_content, reply_content, status, error_message, created_at, replied_at`

其中 `review_content` 可为 `NULL`，`reply_content` 为人工最终确认的 exact 草稿，`status='pending'`，`error_message=NULL`，`replied_at=NULL`。不得接受自由 SQL、动态表名或动态列名。

物理唯一键为 `(hotel_id,channel_source,review_id)`。写入后必须按返回主键和 exact scope 读取，并同时验证：

- `affected_rows=1`
- readback 恰好一行
- hotel/platform/channel/review exact 匹配
- `reply_content` 完全一致
- `status='pending'`

只有全部通过，才能表述“美团回复任务已提交，等待渠道插件处理”。不得声称 OTA 已公开回复。

## 重复、幂等与 CAS 重试

唯一键冲突后必须先读取 exact hotel/channel/review：

- `pending/processing`：返回 `active_conflict`；
- `success`：返回 `already_handled`，不得覆盖；
- `failed/cancelled`：admin/owner/operator 生成新草稿并重新确认后，执行唯一批准的 compare-and-set UPDATE。

CAS 的物理 WHERE 必须包含主键、exact hotel/platform/channel/review、旧状态、旧 `reply_content` 和旧 `created_at`。更新后 `affected_rows` 必须等于 1，并再次进行 exact pending readback。`affected_rows=0` 返回并发冲突，不允许盲目重插。

每次写尝试使用由 hotel/channel/review/draft version/content hash/operation 组成的幂等键。控制面与 MySQL task sink 不是跨系统 ACID；超时、重复事件或响应丢失时必须先 exact readback 对账，并记录 `reconciliation_status=verified|recovered|conflict|unknown`。

旧草稿、确认、写尝试和失败原因保留在 append-only 逻辑事件中。

## 状态观察与输出口径

第三方插件可以把任务更新为 `processing/success/failed/cancelled`。S13 只读观察并发送新的静态状态消息，不更新原卡。

`success` 只表示 task row 的处理状态，不能单独证明 OTA 公开页面已经出现回复。当前固定 `public_reply_verified=false`。只有未来新增独立 Provider 页面/readback 合同后，才能声明公开成功。

最终输出必须符合 `references/output_schema.json`，并明确：资格状态、草稿来源、版本/hash、确认状态、任务状态、写入证据、幂等与 reconciliation、pending readback、风险标记、blocked reason 和 data gaps。
