# close-production-feishu-regressions

## 背景

生产飞书端仍会出现错误出租率、跨群角色信息、硬编码样例指标、错误商品映射、过时数据源话术，以及 S14/商圈/HOS 数据未正确使用的问题。真实库核查显示，部分源表已经补充 `room_type_id`，但 runtime normalization 会把这些字段覆盖成 `None`，导致可调商品和房型维度仍误判为 `mapping_pending`。

## 目标

- 飞书生产问法不再把 `jy01` 昨日/T+1 指标当作今日实时出租率。
- 实时出租率只按 `jd01/jd04` 分子除以 `kf11` 总房减维修分母计算；`kf11` 在住数仅作为房态事实和差异提示，不参与分子。
- runtime 保留真实源表已有的 `room_type_id`，并按 `hotel_room_type_mapping` 与 OTA 商品表动态判定可调候选。
- 生产路径不再混入 demo/sample evidence。
- owner/admin 角色配置、当前群隔离、鉴权话术、数据源话术、S14/商圈/HOS 数据使用按生产口径收敛。

## 影响

- 涉及 MySQL mapping profile、normalizer、实时出租率、进度诊断、飞书 route/render、角色配置、env-check、market/S14 数据适配和测试。
- 不修改生产数据；真实库验收只执行 `SELECT`/只读 runtime 查询。
