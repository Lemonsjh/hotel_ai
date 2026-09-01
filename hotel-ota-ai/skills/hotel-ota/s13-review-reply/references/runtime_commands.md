# S13 评论智能回复受控运行入口

## 边界

S13 不复用 `reputation-diagnosis`，也不使用 V27、OpenClaw、N017/A4 或自由 SQL。所有入口由 `runtime/s13_runtime_patch.py` 接入现有 CLI，并由 `runtime/s13/` 下的独立服务执行。

生产数据要求：

- 评论源：`HOTEL_OTA_S13_SOURCE_DSN`，未设置时可回落到已有 exact-hotel 只读 DSN `HOTEL_OTA_DB_DSN_PUYUE`；
- 评论任务 writer：`HOTEL_OTA_REVIEW_TASK_DSN`；
- 写开关：`HOTEL_OTA_REVIEW_TASK_WRITE_ENABLED=true`；
- writer 只允许对 `ota_review_reply_task` 执行 SELECT、INSERT 和受控 UPDATE。

## 1. 待回复评论

```bash
python runtime/hotel_ota_runtime.py review-reply-list \
  --hotel-id <exact_hotel_id> \
  --principal-role owner \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601>
```

输出只能包含 S12 签发的 opaque `review_ref`、平台、星级、脱敏摘要或“仅评分”、源快照时间和评论时间，不输出物理 review ID。

## 2. 生成草稿

```bash
python runtime/hotel_ota_runtime.py review-reply-draft \
  --hotel-id <exact_hotel_id> \
  --principal-role operator \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --review-ref <opaque_review_ref>
```

服务端重新解析 review ref，并重查 exact 酒店、平台、物理 review、source snapshot 和回复状态。不得从命令行传入平台、物理 review ID 或原评论正文。

## 3. 人工填写或编辑草稿

完整回复写入受控 UTF-8 文件，避免把正文作为 shell 参数进入日志：

```bash
python runtime/hotel_ota_runtime.py review-reply-preview \
  --hotel-id <exact_hotel_id> \
  --principal-role operator \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --review-ref <opaque_review_ref> \
  --reply-file <controlled_utf8_text_file>
```

每次生成或编辑创建新的 `REQ-*`、`draft_version` 和 `content_hash`，并使旧确认失效。人工回复不能为空，最大 2000 字符。

## 4. 确认、拒绝和取消

用户侧只提交 `REQ-*`。版本和 hash 是服务端 sealed request 字段，不要求用户重复输入：

```bash
python runtime/hotel_ota_runtime.py review-reply-confirm \
  --hotel-id <exact_hotel_id> \
  --principal-role owner \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --request-id <REQ-id>

python runtime/hotel_ota_runtime.py review-reply-reject \
  --hotel-id <exact_hotel_id> \
  --principal-role operator \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --request-id <REQ-id>

python runtime/hotel_ota_runtime.py review-reply-cancel \
  --hotel-id <exact_hotel_id> \
  --principal-role operator \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --request-id <REQ-id>
```

确认时服务端重新检查：可信身份、角色、exact 酒店、评论当前状态、sealed version/hash、request expiry、write gate、writer DSN、平台范围和任务幂等状态。

## 5. 查询状态

```bash
python runtime/hotel_ota_runtime.py review-reply-status \
  --hotel-id <exact_hotel_id> \
  --principal-role owner \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --request-id <REQ-id>
```

也可以使用 opaque ref 查询：

```bash
python runtime/hotel_ota_runtime.py review-reply-status \
  --hotel-id <exact_hotel_id> \
  --principal-role owner \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --review-ref <opaque_review_ref>
```

`success` 只表示 task row 状态，不渲染成 OTA 页面公开回复成功。

## 6. failed/cancelled CAS 重试

先生成新草稿和新 `REQ-*`，再执行：

```bash
python runtime/hotel_ota_runtime.py review-reply-retry \
  --hotel-id <exact_hotel_id> \
  --principal-role owner \
  --principal-ref <trusted_principal_ref> \
  --as-of <ISO-8601> \
  --request-id <new_REQ_id>
```

只允许 exact `failed/cancelled` 任务执行 CAS UPDATE。WHERE 必须包含主键、exact hotel/platform/channel/review、旧状态、旧 reply content 和旧 created_at；随后要求 `affected_rows=1` 和 exact pending readback。

## 通用运行规则

- 只有 owner/operator 可以查看、生成、编辑、确认、查询和重试；frontdesk/viewer 无任务权限；admin/guest 不作为 S13 业务角色。
- 只有美团可以写任务；大众点评、携程、去哪儿、同程和智行只能复制草稿。
- `review_content=NULL` 是合法纯评分评论，不是 data gap。
- 高风险评论进入 `blocked_escalation`，不生成可提交草稿。
- 第一次提交只允许固定 INSERT；唯一键冲突先 exact 读取，禁止盲目重插。
- 控制面写尝试使用幂等键并记录 reconciliation 状态，跨系统超时后先 readback 对账。
- 未同时满足 `affected_rows=1` 和 `pending_readback_verified=true`，不得声称任务已提交。
