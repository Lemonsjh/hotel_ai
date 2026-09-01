# S2 经营房态采集 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py feishu-route --message "实时出租率" --production-feishu --chat-id <trusted_chat_id> --open-id <trusted_sender_id>`
- `python runtime/hotel_ota_runtime.py expected-occupancy --hotel-id puyue --date <target_business_date> --as-of-time <as_of_time>`
- `python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue`（历史/兼容经营快照，不用于当前实时出租率）
- `python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-room-count`
- `python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-inventory`
- `python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode columns --table kf11_room_status_snapshot`
- `python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template operating_snapshot --hotel-id puyue`

## 规则
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须加审批和 dry-run 预览。
- 生产 Feishu 的“实时出租率 / 当前出租率”必须通过 `feishu-route --production-feishu` 或 `expected-occupancy` 统一公式取得，不得使用 `snapshot` / `jy01_hotel_statistics_daily.occupancy_rate`。
- `target_business_date` 是 runtime 从请求当天或用户显式日期解析出的目标业务日期，不是 `jd01.business_date` 字段。
- 统一公式为 `jd01` 已入住且 `departure_time > as_of_time` + `jd01` 当日有效预订/取消按 `DATE(arrival_time)=target_business_date` 统计（按订单号去重并扣当日取消）+ `jd04` 续住，分母为 `kf11` 总房减维修房。
- API 未确认时优先使用 `normalize-sample`、manual upload 或 RPA 输入，并标注 demo/sample。
- MySQL 报表库必须通过 `/etc/hotel-ota-ai/database-source.json` 映射，不得直接生成自由 SQL。
