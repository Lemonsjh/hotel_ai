# S13 评论智能回复规则

## 1. 输入与服务端定位

- 唯一业务定位输入是 S12 签发的 opaque `review_ref`。
- ref 的酒店、平台、物理 `review_id`、source snapshot、内容摘要和过期时间只存服务端；可见 token 不编码这些信息。
- 服务端必须在当前 `RequestContext.hotel_id` 下解析 ref，并重新查询 exact 酒店、平台、物理 review、星级、正文和 `is_replied`。
- 用户输入中的 `hotel_id/platform/review_id/review_content` 不得覆盖服务端解析结果。
- 原评论身份、酒店/POI、图片 URL、客人、订单和房号不得进入 AI、卡片或任务审计正文。
- 第一版不读取评论图片正文。

## 2. 权限

- `admin`、`owner`、`operator`：均可查看待回复、生成/编辑草稿、确认、取消、查询和受控重试。
- 若 capability policy 要求独立审批，申请人与确认人不得相同，由另一名具有评论回复权限的 admin/owner/operator 完成；不得解释成只有 owner 可以确认。
- `frontdesk`、`viewer`、`guest`：无评论回复任务权限。
- admin 仍必须经过 S13 的 exact 酒店范围、确定性风险检查、版本确认、write gate、writer grant、幂等和 pending readback，不能绕过业务安全规则。

## 3. 待回复队列与数量口径

S13 的 `待回复评论` 必须直接复用 S12 的评论明细口径，不得使用 overview 的 `unreplied_review_count` 替代评论级队列，也不得把多个平台合并后再猜测平台归属。

固定计算顺序：

1. 固定 exact `RequestContext.hotel_id` 和 `as_of_datetime`；
2. 使用最近 60 日评论明细窗口，业务时间取 `review_time`，抓取/知识截止取 `snapshot_time<=as_of_datetime`；
3. 美团族以 `review_platform` 为优先平台字段，规范映射为 `meituan`（美团）或 `dianping`（大众点评）；携程族使用 `platform_scope`；
4. 按 `hotel_id + platform + review_id` 取截至 as-of 的最新 snapshot；
5. 只把最新记录明确满足 `is_replied=0` 的评论计入，空值或未知回复状态不得当作未回复；
6. `review_content=NULL` 的纯评分评论仍计入；
7. 完成 exact scope、窗口、去重和回复状态判断后，才能排序、分页或应用展示 `limit`。

飞书必须同时显示总数和逐平台数量，例如：`待回复评论：共22条（美团19条，大众点评3条）`。当前 2026-08-03 验收快照的正确结果为 22 条，其中美团 19 条、大众点评 3 条；该数字是数据验收值，不得硬编码到业务逻辑。

## 4. 资格判定

创建草稿前同时检查：

1. exact 酒店和平台仍匹配；
2. `is_replied=0`；
3. `review_ref` 未过期；
4. source snapshot 和内容 digest 未变化；
5. 当前角色、权限和 capability policy 有效；
6. 同 review 不存在 active `pending/processing` 任务。

状态处理：

- `pending/processing`：`active_conflict`；
- `success`：`already_handled`，不得覆盖；
- `failed/cancelled`：只能进入新草稿、新确认、CAS 重试；
- 高风险规则命中：`blocked_escalation`，不得形成可提交草稿。

高风险包括安全、隐私、歧视、威胁、伤害、法律争议、索赔和重大舆情。

## 5. 纯评分评论

- 源记录和任务表中的 `review_content` 均允许为 `NULL`。
- 纯评分评论不得标记为缺失，也不得被过滤。
- 使用星级和批准语气生成确定性通用草稿，不调用模型编造不存在的正文。
- 允许为空的是源评论正文，不是最终 `reply_content`；人工回复必须为 1–2000 字符。

## 6. 清洗与候选

非空正文先清洗 URL、电话、邮箱、身份证/订单号、房号、联系方式、疑似姓名和重复空白，再运行 S12 的主题、否定和紧急度规则。

普通非空评论每条消息最多一次 `business_analysis/content_drafting`。模型不可用、超时或 Schema 失败时，使用确定性模板，不阻塞人工草稿。模板按 `template_key` 区分：`positive_review`（普通好评）、`high_rating_negative_feedback`（4–5 星但正文含投诉信号或来源差评）、`negative_review`（≤3 星或来源差评）和 `neutral_feedback`。候选固定包含：

```json
{
  "draft": "string",
  "tone": "neutral|professional|warm|apologetic",
  "acknowledged_topics": ["approved_topic"],
  "risk_flags": ["approved_flag"],
  "requires_human_escalation": false
}
```

候选生成后检查最大 2000 字符、PII、未批准承诺、虚构事实和主题白名单。禁止自动生成退款、赔偿、升级房型、处罚员工、删除评论、线下联系、已修复或已公开回复等承诺。

## 7. 草稿版本与文本确认

- 每次生成或人工编辑产生新 `draft_version`、`content_hash=sha256:<64hex>` 和新 `REQ-*`。
- 新版本生成后，旧请求立即变为 `invalidated_by_new_version`。
- 用户侧只发送 `确认/拒绝/取消/查询/重试 REQ-*`，不发送 version/hash。
- 服务端从 sealed request 读取 expected version/hash，并与当前最新草稿重新比对。
- 不使用按钮、callback 或原卡更新。
- 确认时重新检查用户、角色、酒店、review 状态、request 是否最新、过期、write gate、writer grant、自批策略和幂等写尝试。

## 8. 平台写入范围

当前只有美团可写任务：

```text
platform = meituan
channel_source = meituan
```

大众点评、携程、去哪儿、同程和智行只能生成、编辑和复制草稿，必须返回 `copy_only=true`、`task=null`。

## 9. 固定 INSERT

目标表：`ota_review_reply_task`。唯一允许写入的列为：

```text
hotel_id, platform, channel_source, review_id,
review_content, reply_content, status, error_message,
created_at, replied_at
```

首次提交只能执行固定参数化 INSERT：

```sql
INSERT INTO ota_review_reply_task (
  hotel_id, platform, channel_source, review_id,
  review_content, reply_content, status, error_message,
  created_at, replied_at
) VALUES (
  :hotel_id, 'meituan', 'meituan', :review_id,
  :review_content, :reply_content, 'pending', NULL,
  :created_at, NULL
);
```

`hotel_id`、`review_id` 和 `review_content` 均来自 exact server-side record；纯评分时 `review_content=NULL`；`reply_content` 是人工最终确认的 exact 草稿。字段名不得写成 `reply_cotent`。

## 10. exact pending readback

写入后必须使用返回主键和 exact scope 读取，并验证：

- `affected_rows=1`；
- readback 恰好一行；
- hotel/platform/channel/review exact 匹配；
- `reply_content` 与 sealed 草稿完全一致；
- `status='pending'`。

只有全部通过才能表述：“美团回复任务已提交，等待渠道插件处理。”

## 11. 唯一键、幂等与 CAS

唯一键：`(hotel_id, channel_source, review_id)`。

唯一键冲突先 exact 读取：

- `pending/processing`：active conflict；
- `success`：already handled；
- `failed/cancelled`：新草稿、新 REQ 确认后 CAS 重试。

CAS WHERE 必须包含主键、exact hotel/platform/channel/review、旧状态、旧 `reply_content` 和旧 `created_at`。更新字段固定为 `review_content,reply_content,status='pending',error_message=NULL,created_at,replied_at=NULL`。`affected_rows=0` 返回并发冲突，不重插；`affected_rows=1` 后必须再次 exact pending readback。

每次写尝试使用由 hotel/channel/review/draft version/content hash/operation 组成的幂等键。控制面与 MySQL sink 不是跨系统 ACID；超时或重复事件必须先 readback 对账，并记录 `reconciliation_status=verified|recovered|conflict|unknown`。

## 12. 状态观察

第三方插件可更新为 `processing/success/failed/cancelled`。S13 只读观察并发送新静态消息。

`success` 仅代表 task row 处理状态，不证明 OTA 页面公开成功；当前固定 `public_reply_verified=false`。

## 13. data gap 与禁止事项

以下情况返回明确 data gap 或 blocked reason：ref 无法解析或过期、exact 酒店记录不存在、source snapshot 变化、权限或 writer grant 缺失、非美团请求写任务、DML affected rows 不为 1、pending readback 不一致、CAS 比较失败或跨系统对账未知。

不得恢复 V27、OpenClaw、N017/A4、guest、自动补偿、自动私信、自由 SQL 或自动公开发布语义。
