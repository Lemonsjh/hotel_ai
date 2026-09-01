# S6 房价同步执行 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py execute-price --hotel-id puyue --room-type-id <统一房型ID> --ota-product-id <OTA商品ID> --channel-source meituan --normal-price 159 --begin-date 2026-06-02 --end-date 2026-06-02 --approved-by boss --dry-run`
- `python runtime/hotel_ota_runtime.py price-task-history --channel-source meituan --hotel-name '<hotel_name>'`（查调价历史）
- `python runtime/hotel_ota_runtime.py adapter-request --adapter beyondh --method Price.SetPriceByRoomTypeId --biz-content "{}"`

## 规则
- **按商品精确调价**：同房型多个商品价差大（挂牌/团购/钟点），必须用 `--ota-product-id` 指定；不指定且多商品时会被 `price_task_requires_ota_product_id` 拒绝并返回候选清单，不得把一个价灌给全部商品。
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须加审批和 dry-run 预览。
- API 未确认时优先使用 `normalize-sample`、manual upload 或 RPA 输入。
