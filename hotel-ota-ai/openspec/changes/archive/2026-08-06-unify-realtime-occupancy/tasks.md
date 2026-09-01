## 1. Spec

- [x] 1.1 编写统一实时出租率和销售基准线 OpenSpec。
- [x] 1.2 通过 `openspec validate unify-realtime-occupancy --strict`。

## 2. Tests

- [x] 2.1 增加实时出租率公式、去重、dirty/maintenance 分母测试。
- [x] 2.2 增加 S5 使用统一实时出租率测试。
- [x] 2.3 增加 S16 使用 occupancy rate 主判断测试。
- [x] 2.4 增加 baseline fallback curve 低置信且不可自动调价测试。
- [x] 2.5 增加 jy01/rs01 对齐验证命令测试。
- [x] 2.6 增加 S2/S14 输出统一实时出租率证据测试。

## 3. Implementation

- [x] 3.1 增加统一实时出租率 helper/template。
- [x] 3.2 修改 `expected_occupancy_result()` 复用统一口径。
- [x] 3.3 修改 `deviation()` 以出租率对比作为主判断。
- [x] 3.4 修改 baseline 输出 target occupancy checkpoint 曲线和 fallback policy。
- [x] 3.5 保持历史日 jy01/rs01 与实时 jd01/jd04/kf11 粒度分离。
- [x] 3.6 增加 jy01/rs01 只读对齐验证命令。
- [x] 3.7 修改 S2/S14 输出统一实时出租率证据。

## 4. Verification

- [x] 4.1 运行相关 focused tests。
- [x] 4.2 运行 OpenSpec validate 和 diff 检查。
