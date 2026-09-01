# 酒店 OTA Skill 共享契约

所有酒店 OTA skill 都必须遵守本契约。业务说明使用中文；技术标识、API 方法、命令、JSON 字段保持英文。

## 安全底线

- 调价、改房量、改房态、推广执行、公开评论回复都不能默认真实执行。
- 没有 admin/owner 审批时，只能返回 dry-run 建议和待审批动作。
- 飞书来源必须先完成身份校验；未进入角色表的用户视为 `guest`，不得触发业务 skill。
- 真实写动作审批人必须是 `admin` 或 `owner`，不能只凭 `approved_by` 文本放行。
- 不得输出 Beyondh `ChannelKey`、`AppKey`、`Sign`、密码、验证码、OTA/PMS 账号密钥。
- 小满、超级店长、甩手掌柜只是业务参考，不是验收标准。
- 美团 API、Beyondh API、订单来了 API 都只是渠道适配参考，不是 P0/P1 的硬依赖。

## 标准输入

- `hotel_id`：酒店内部标识；演示默认 `puyue`。
- `user_role`：`admin`、`owner`、`operator`、`frontdesk`、`guest`。
- `auth_context`：身份上下文；包括 `source`、`auth_status`、飞书用户/群 ID 和权限列表。
- `trigger`：`chat`、`cron`、`manual_test`、`approval`。
- `date_range`：营业日期或日期范围。
- `channels`：OTA/PMS 渠道。
- `mode`：`diagnose`、`recommend`、`dry_run`、`approved_execute`。
  - `adapter_vendor`：`beyondh | meituan | dindanll | xhotel | manual | database`。
- `channel_source`：`meituan | feizhu | douyin | ctrip | wechat | pms | manual`。
  - `data_source_type`：`meituan_api | beyondh_api | dindanll_api | sqlite_db | mysql_db | postgres_db | rpa | manual_upload | sample_data`。
- `source_capability`：`read_only | write_dry_run | write_live_pending | unavailable`。
- `field_quality`：`confirmed | inferred | manual_required | unavailable`。
- `data_business_date`：业务数据所属营业日期。
- `data_snapshot_time`：业务数据快照或导入时间。
- `freshness_status`：`fresh | stale | missing_date | demo_data`。
- `data_age_hours`：数据距当前时间的小时数。
- `business_status`：`current | demo_or_historical`。
- `today_label_allowed`：是否允许使用“今日/实时”口径。

## 标准输出

聊天中先给简洁中文结论；需要结构化数据时附带：

```json
{
  "status": "ok | dry_run | blocked | error",
  "skill_id": "Sxx",
  "summary": "human readable result",
  "evidence": [],
  "recommendations": [],
  "actions": [],
  "risk_level": "low | medium | high",
  "approval_required": true,
  "data_business_date": "2026-06-04",
  "data_snapshot_time": "2026-06-04 10:00:00",
  "freshness_status": "fresh",
  "data_age_hours": 2.0,
  "business_status": "current",
  "today_label_allowed": true,
  "next_run_at": null,
  "artifacts": []
}
```

## 动作类型

- `price_update`
- `quota_update`
- `promotion_update`
- `review_reply`
- `notify`
- `diagnosis_task`
- `data_collection`

## 角色权限

- `admin`：超级管理员；可管理角色表、安全配置、所有 skill、所有审批和紧急停用。
- `owner`：老板；可查看全部业务结果、审批真实执行、调整业务安全阈值。
- `operator`：运营；可触发诊断、生成建议、发起审批、执行 dry-run，不可批准 live。
- `frontdesk`：前台；只能接收任务、上传截图、反馈完成，不可触发调价、推广或口碑发布。
- `guest`：未授权用户；飞书中只返回无权限提示，不读取业务数据，不触发业务 skill。

权限动作统一使用：

```text
view_diagnosis
run_recommendation
create_dry_run
create_approval
approve_live_action
execute_live_action
manage_roles
manage_safety_config
```

## 运行时命令

当 skill 需要本地执行时，调用：

```bash
python runtime/hotel_ota_runtime.py --help
```

常用命令：

```bash
python runtime/hotel_ota_runtime.py init-db
python runtime/hotel_ota_runtime.py seed-demo
python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py baseline --hotel-id puyue
python runtime/hotel_ota_runtime.py deviation --hotel-id puyue
python runtime/hotel_ota_runtime.py revenue-decision --hotel-id puyue
python runtime/hotel_ota_runtime.py demand-index --hotel-id puyue
python runtime/hotel_ota_runtime.py ota-health --hotel-id puyue
python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id puyue
python runtime/hotel_ota_runtime.py competition-alert --hotel-id puyue
python runtime/hotel_ota_runtime.py frontdesk-tasks --hotel-id puyue
python runtime/hotel_ota_runtime.py reputation-diagnosis --hotel-id puyue
python runtime/hotel_ota_runtime.py adapter-request --adapter meituan --path /pms/priceinve/getRoomPrice --biz-content '{"hotelId":600000001,"channel":"MeiTuanEBK","roomTypeIds":["KING"]}'
python runtime/hotel_ota_runtime.py adapter-request --adapter dindanll --path /open/pms/third/ari/price --biz-content '{"hotelNum":10001,"roomTypeCodeList":[9001],"rateCode":30}'
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-price
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-order
```

## Reference 加载规则

每个 skill 都必须先读取本目录下的 `references/` 五件套：

- `input_schema.json`
- `output_schema.json`
- `rules.md`
- `examples.md`
- `runtime_commands.md`

`SKILL.md` 负责触发和导航，详细业务规则、字段和样例以 references 为准。

## P0/P1 交付优先级

2026-06-15 前必须优先保证 `S1/S2/S3/S14/S15/S16/S4/S5/S6 + OpenClaw 总控配置` 可演示。P2 skill 可以加载，但不得阻塞 6 月 15 日闭环。

## 统一数据契约

所有 skill 优先读取 `requirements/统一数据契约.md` 中定义的统一对象。API 未确定时，使用 `sample_data`、`manual_upload` 或 `rpa` 兜底，不允许因为某个 API 未开通而中断 P0/P1。

## 脚本固化边界

签名验签、token、请求构造、字段映射、状态码转换、JSON 校验、身份权限、审批拦截、日志脱敏、dry-run 动作生成必须优先由 `runtime/` 包固化；`runtime/hotel_ota_runtime.py` 保留为兼容 CLI 入口。skill/模型负责中文解释、缺失信息追问、飞书回复、策略取舍和 admin/owner 审批沟通。

## 飞书输出边界

生产飞书回复必须先遵守 runtime `feishu-output-gate` 语义。允许输出脱敏摘要、诊断结论、证据日期、数据新鲜度、风险、建议动作和审批状态；禁止输出配置包、env、auth profile、角色表、数据库映射、源码包、CSV/XLSX/JSON 原始数据、完整 runtime JSON、代码片段、真实 `open_id/chat_id`、DSN 或 API 请求体。

正式审批 payload 必须包含 `dry_run_summary`、`data_business_date`、`data_snapshot_time`、`freshness_status`。`sample_data`、`demo_data`、`stale`、`missing_date` 只能用于历史/演示分析，不得创建正式审批或进入 live 执行。
