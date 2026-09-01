# S13 评论智能回复示例

## 1. 获取待回复评论

```json
{
  "request_context": {
    "hotel_id": "puyue",
    "as_of_datetime": "2026-08-03T16:00:00+08:00",
    "principal_role": "operator",
    "principal_ref": "principal:opaque"
  },
  "action": "list_pending"
}
```

输出只展示 opaque ref，不展示物理 review ID：

```json
{
  "status": "ok",
  "action": "list_pending",
  "items": [
    {
      "review_ref": "REV-opaque-token",
      "platform": "meituan",
      "star_rating": 2,
      "review_content_present": true,
      "redacted_excerpt": "房间卫生一般，[电话已隐藏]",
      "source_snapshot": "2026-08-03T15:55:00+08:00"
    }
  ]
}
```

## 2. 普通美团评论生成草稿

```json
{
  "request_context": {
    "hotel_id": "puyue",
    "as_of_datetime": "2026-08-03T16:01:00+08:00",
    "principal_role": "operator",
    "principal_ref": "principal:opaque"
  },
  "action": "generate_draft",
  "review_ref": "REV-opaque-token"
}
```

```json
{
  "status": "ok",
  "action": "generate_draft",
  "platform": "meituan",
  "eligibility_status": "eligible",
  "draft_candidate": {
    "draft": "非常抱歉本次入住体验未达到您的预期。您反馈的卫生问题我们已经记录，并会继续加强现场检查与服务流程。感谢您的意见，也欢迎您再次向我们反馈体验。",
    "tone": "apologetic",
    "acknowledged_topics": ["cleanliness"],
    "risk_flags": [],
    "requires_human_escalation": false,
    "candidate_origin": "deterministic_candidate",
    "draft_version": 1,
    "content_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "confirmation": {
    "request_id": "REQ-review-001",
    "status": "confirmation_pending",
    "expires_at": "2026-08-03T16:31:00+08:00",
    "draft_version": 1,
    "content_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "task": null,
  "copy_only": false
}
```

用户只需发送：

```text
确认 REQ-review-001
```

不需要重复输入 version/hash；服务端从 sealed request 读取并校验。

## 3. 纯评分评论

源记录 `review_content=NULL` 时仍生成确定性草稿：

```json
{
  "status": "ok",
  "action": "generate_draft",
  "platform": "meituan",
  "star_rating": 5,
  "review_content_present": false,
  "draft_candidate": {
    "draft": "感谢您的评价与支持。我们会继续用心做好每一项服务，也欢迎您下次入住后继续向我们分享体验。",
    "tone": "warm",
    "acknowledged_topics": [],
    "risk_flags": [],
    "requires_human_escalation": false,
    "candidate_origin": "deterministic_candidate",
    "draft_version": 1,
    "content_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
```

## 4. 非美团平台只复制草稿

```json
{
  "status": "ok",
  "action": "generate_draft",
  "platform": "ctrip",
  "draft_candidate": {
    "draft": "感谢您的反馈，我们已关注您提到的体验问题，并会持续检查服务细节。",
    "tone": "professional",
    "acknowledged_topics": ["service_response"],
    "risk_flags": [],
    "requires_human_escalation": false,
    "candidate_origin": "deterministic_candidate",
    "draft_version": 1,
    "content_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "confirmation": null,
  "task": null,
  "copy_only": true
}
```

## 5. 人工编辑使旧确认失效

人工编辑创建新 `REQ-*` 和版本 2。旧请求状态变为：

```json
{
  "request_id": "REQ-review-001",
  "status": "invalidated_by_new_version",
  "draft_version": 1
}
```

## 6. 美团确认与 pending readback

确认输入：

```json
{
  "request_context": {
    "hotel_id": "puyue",
    "as_of_datetime": "2026-08-03T16:10:00+08:00",
    "principal_role": "owner",
    "principal_ref": "principal:opaque"
  },
  "action": "confirm",
  "request_id": "REQ-review-002"
}
```

成功输出：

```json
{
  "status": "ok",
  "action": "confirm",
  "platform": "meituan",
  "confirmation": {
    "request_id": "REQ-review-002",
    "status": "confirmed",
    "expires_at": null,
    "draft_version": 2,
    "content_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  },
  "task": {
    "task_ref": "TASK-1",
    "platform": "meituan",
    "channel_source": "meituan",
    "status": "pending",
    "write_performed": true,
    "affected_rows": 1,
    "pending_readback_verified": true,
    "provider_status_observed": false,
    "public_reply_verified": false,
    "retry_mode": null,
    "reconciliation_status": "verified",
    "idempotency_verified": true
  },
  "copy_only": false
}
```

用户文案只能是：“美团回复任务已提交，等待渠道插件处理。”

重复投递同一个 `确认 REQ-*` 时，不再次写入，而是返回既有任务并标记：

```json
{
  "idempotent_replay": true,
  "task": {
    "write_performed": false,
    "affected_rows": 0,
    "reconciliation_status": "recovered",
    "idempotency_verified": true
  }
}
```

## 7. active conflict 与 already handled

- 已有 `pending/processing`：`status=active_conflict`，不 INSERT、不 UPDATE；
- 已有 `success`：`status=already_handled`，不覆盖，`public_reply_verified=false`。

## 8. failed/cancelled CAS 重试

先生成新草稿和新 `REQ-*`，然后：

```json
{
  "action": "retry",
  "request_id": "REQ-review-retry-001"
}
```

CAS 成功输出 `retry_mode=cas_update`、`affected_rows=1`、`pending_readback_verified=true`。比较失败时返回 write failure，不重插。

## 9. 高风险评论

```json
{
  "status": "blocked",
  "action": "generate_draft",
  "eligibility_status": "blocked_escalation",
  "draft_candidate": null,
  "confirmation": null,
  "task": null,
  "blocked_reason": "legal_or_claim_escalation",
  "risk_flags": ["legal_dispute", "claim"]
}
```

不得自动生成补偿、私信或可提交公开回复。
