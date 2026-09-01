## Design

### CLI 入口

`runtime.cli` 已有 `main(argv=None)` 和完整 argparse 配置，缺口只在文件末尾没有模块入口。补齐：

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

这样 `python -m runtime.cli --help` 会走同一套 parser，`database-query` 也会通过 `args.func(args)` 输出 JSON。

### 价格任务表 readiness

`is_price_task_mapping_ready()` 只负责判断商品是否具备写入价格任务表的基础映射资格：

- 可信身份：`match_rule` 命中可信规则，或 `mapping_status=CONFIRMED`
- mapping active
- `room_type_id` 存在
- `source_product_id` 存在
- 平台未禁用
- 携程仍要求 `product_cipher`

`price_editable_flag` 与 `is_hour_room` 不再设置 `blocked_reason`。调用方仍可把这些字段作为信息返回，用于展示商品类型和插件侧能力。

### Outbox 商品筛选

`_product_skip_reason()` 复用 readiness 后，不再额外因为携程 `price_editable_flag` 阻断。携程仅继续要求 `product_cipher`，因为这是插件执行携程任务所需字段。

## Risks

- 如果插件真实侧仍对某些商品类型有限制，runtime 会允许写任务表，后续由插件回查或执行状态返回失败。该失败不能在 runtime 里用旧商品类型规则提前硬拦。
- 钟点房和团购价格跨度大，调用方必须继续按 `ota_product_id` 精确选择商品，不能用房型级价格覆盖多个商品。
