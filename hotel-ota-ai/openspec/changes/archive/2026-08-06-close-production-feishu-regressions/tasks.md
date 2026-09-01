# Tasks

- [x] 1. 补齐生产飞书红灯测试和真实库结构 fixture。
- [x] 2. 更新 MySQL profile 与映射读取，默认使用 `hotel_room_type_mapping`，视图仅作兼容。
- [x] 3. 修复 normalizer 保留源表已有 `room_type_id`。
- [x] 4. 对齐实时出租率公式，`kf11` 只做分母和辅助房态事实。
- [x] 5. 移除生产 `data_gap` 路径中的 demo/sample evidence。
- [x] 6. 修复 owner 配置 owner、当前群隔离、鉴权/数据源话术。
- [x] 7. 修复可调商品查询动态映射逻辑和 `price_editable_flag` 依赖。
- [x] 8. 修复商圈/HOS/S14 真实数据读取和 S14-EXT 解耦。
- [x] 9. 运行 OpenSpec、单元测试和真实库只读验收。
- [x] 10. 补齐 S2 / Feishu Auth Guard skill 文档门禁，防止外层 agent 继续用旧 `snapshot` 口径或误报群未绑定。
- [x] 11. 收紧实时出租率 `target_business_date` / `as_of_time` 语义，禁止用快照时间、最新日结或昨天数据兜底。
