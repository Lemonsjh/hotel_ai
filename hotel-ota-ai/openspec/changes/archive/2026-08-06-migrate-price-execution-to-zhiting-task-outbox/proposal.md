## Why

当前 S6 `execute-price` 仍围绕 Beyondh/OTA API 请求构造执行路径。生产试验前，调价执行必须改为写入 MySQL/SQLite 兼容的 `ctrip_zhiting_price_task`、`meituan_zhiting_price_task` 任务表，由执行插件读取 `PENDING` 后执行并回写 `SUCCESS/FAILED`。AI/OpenClaw 不再直接调用 OTA 调价 API。

## What Changes

- 新增 zhiting price task outbox 写入模型和 schema 迁移，只新增字段，不删除现有字段。
- S6 在确认、鉴权、护栏和商品映射通过后，把房型建议价展开到所有可调 OTA 商品，并写入 `PENDING` 任务。
- `business_date` 固定表示售卖日/入住业务日期，`created_at` 表示任务创建时间。
- `execute_status` 第一版只允许 `PENDING/SUCCESS/FAILED`；AI 只能写 `PENDING`。
- 旧 direct API live adapter 默认降级为 deprecated，调用时返回受控 blocked 原因。
- env-check、飞书输出和根上下文文件改为描述任务表执行路径，不再建议打开 live API 开关。

## Impact

影响 `runtime/decisions/pricing.py`、新增任务 outbox 模块、SQLite 运行库 schema、CLI 参数、env-check、Feishu 渲染、OpenClaw 根上下文文档和测试。不会连接真实 OTA API，不会删除现有 MySQL 字段，不会自动修改 `/etc` 或生产数据库。
