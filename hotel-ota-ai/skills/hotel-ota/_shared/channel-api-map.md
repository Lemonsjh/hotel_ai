# 渠道 API 适配映射

本文件用于统一 Beyondh、美团、订单来了、RPA、人工上传和样例数据。任何 skill 都不要直接依赖某个原始 API 字段，而是读取统一数据契约。

## 适配原则

- API 只是数据源，不是 P0/P1 验收前提。
- 美团 API、Beyondh API、订单来了 API 的具体权限、字段、签名和回调方式都待账号/商务权限确认。
- API 不可用时，使用 `manual_upload`、`rpa` 或 `sample_data` 进入统一字段。
- 写操作默认 `dry_run`，真实执行必须 admin/owner 审批。

## 标准来源字段

- `adapter_vendor`: `beyondh | meituan | dindanll | xhotel | manual | database`
- `channel_source`: `meituan | feizhu | douyin | ctrip | wechat | pms | manual`
- `data_source_type`: `meituan_api | beyondh_api | dindanll_api | sqlite_db | mysql_db | postgres_db | rpa | manual_upload | sample_data`
- `source_capability`: `read_only | write_dry_run | write_live_pending | unavailable`
- `field_quality`: `confirmed | inferred | manual_required | unavailable`

## 数据库报表库入口

- MySQL 报表库只作为 `adapter_vendor=database`、`data_source_type=mysql_db` 的只读来源。
- `import_batches` 只做导入批次和数据血缘；不得直接当经营、价格或订单结论。
- `fact_room_status_snapshot` 映射经营快照；`fact_daily_metrics` 和 `fact_monthly_metrics` 映射日/月经营指标；`fact_room_fee_daily` 映射价格快照和订单分析。
- 表名、字段名、指标别名、房态别名必须来自 `/etc/hotel-ota-ai/database-source.json`，不得在 skill 中硬写自由 SQL。
- `guest_name`、`room_no`、`order_no`、`operator_name` 默认脱敏，飞书回复不得展示完整敏感值。

## 美团参考入口

- 美团技术服务合作中心 API 文档：`https://developer.meituan.com/docs/api`
- 美团酒店门票分销平台：`https://developer-distribution.meituan.com/`

注意：分销平台偏酒店供给/分销预订链路，不等同于酒店商家侧 OTA 运营后台 API。商家侧 HOS、曝光、浏览、支付转化、活动和评论等字段仍需以账号权限或后台导出结果确认。

## 美团优先映射字段

P0/P1 优先：

- HOS 总分及构成。
- 房型可售状态。
- 每日挂牌价、每日促销价。
- 每日已售房量、每日可售房量、每日总房量。
- 曝光量、浏览人数、支付转化率、订单量。
- 评分、差评率、评价内容。

P2 再映射：

- 活动配置。
- 推广余额、推广消耗。
- 竞品价格、竞品活动、同行排名。
- 客户订单画像。

## Beyondh PMS 参考接口

读取：

- `Hotel.GetOrgRoomTypes`：查询酒店房型。
- `Ota.GetOtaRoomTypesByOrgId`：查询指定 OTA 渠道房型。
- `RoomType.GetRealTimeRentRateByRoomTypeId`：查询在住、预抵、预离、维修、出租率。
- `Hotel.SearchOrgWithRoomPriceAndRoomCount`：查询房价、最低价、房量和日期明细。
- `Hotel.GetChannelQuota`：查询渠道配额。
- `Hotel.GetRoomStatus`：查询房态。
- `Order.QueryOrders`：订单列表。
- `Order.QuerySingleOrder`：单订单详情。

写入参考：

- `Price.SetPriceByRateCode`：按房价码修改固定价。
- `Price.SetPriceByRoomTypeId`：按房型修改 Mtop/QZAgent 渠道平日价/周末价。
- `Room.ModifyRoomStatus`：修改房态，P0/P1 不默认开放真实执行。

## 订单来了 PMS/直连中台参考接口

订单来了作为 `adapter_vendor=dindanll`、`data_source_type=dindanll_api`，业务归属通常为 `channel_source=pms`。它不是 OTA 渠道，而是 PMS/直连中台参考源。

读取：

- `/open/pms/third/hotel/fetch`：酒店信息查询。
- `/open/pms/third/hotel/listRooms`：酒店房型基础信息查询。
- `/open/pms/third/hotel/listRoomTypeStaticInfo`：酒店房型静态信息查询。
- `/open/pms/third/hotel/listRateCode`：房价码信息查询。
- `/open/pms/third/ari/price`：房型价格查询。
- `/open/pms/third/ari/inv`：房型库存查询。
- `/open/pms/third/order/get`：查询订单。

写入或流程参考：

- `/open/pms/third/order/trial`：可订检查。
- `/open/pms/third/order/commit`：提交订单。
- `/open/pms/third/order/accept`：接单/拒单确认。
- `/open/pms/third/order/cancel`：取消订单。

推送事件参考：

- 房价变更通知。
- 房态变更通知。
- 订单接单、拒单、入住、退房通知。

注意：订单来了真实调用涉及 RSA2/SHA1withRSA、AES 解密、门店调用凭证和回调验签。P0/P1 只要求 dry-run 请求构造和字段归一化。

## Beyondh 公共协议参考

- 请求体字段：`ChannelKey`、`Method`、`BizContent`、`Format`、`Charset`、`Version`、`Timestamp`、`SignType`、`Sign`。
- HTTP Header：`Content-Type: application/json` 和 `domain`。
- 签名：排除 `Sign` 后按参数名 ASCII 升序拼接为 `key=value`，空值参与签名，末尾追加 AppKey，使用 `MD5` 或 `SHA256` 加密，结果转大写。

## 执行保护

- 写接口默认 dry-run。
- 真实调用必须满足对应渠道 live 开关，例如 `BEYONDH_ENABLE_LIVE=1`。
- 真实调用必须有 admin/owner 审批记录。
- 日志只能记录脱敏请求摘要和响应码，不记录密钥。

## Runtime 适配命令

```bash
python runtime/hotel_ota_runtime.py demand-index --hotel-id puyue
python runtime/hotel_ota_runtime.py ota-health --hotel-id puyue
python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id puyue
python runtime/hotel_ota_runtime.py adapter-request --adapter meituan --path /pms/priceinve/getRoomPrice --biz-content '{"hotelId":600000001,"channel":"MeiTuanEBK","roomTypeIds":["KING"]}'
python runtime/hotel_ota_runtime.py adapter-request --adapter dindanll --path /open/pms/third/ari/price --biz-content '{"hotelNum":10001,"roomTypeCodeList":[9001],"rateCode":30}'
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-price
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-room-count
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-price
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-inventory
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-order
```
