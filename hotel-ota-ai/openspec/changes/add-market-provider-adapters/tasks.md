## 1. Provider normalization

- [x] 1.1 为 provider 优先级、不可用和降级状态增加测试。
- [x] 1.2 实现统一 weather/event normalization。
- [x] 1.3 接入 S4/S9，并限制活动搜索只作为置信度受限信号，不直接触发调价。

## 2. S4 Feishu routing and deployment config

- [x] 2.1 飞书 `s4/S4/s04/行情/环境行情感知` 命中 `market_context_demo`。
- [x] 2.2 `market_context_demo` 调用 runtime `market-context`，读取 `HOTEL_OTA_MARKET_SOURCE_CONFIG` 或默认 `/etc/hotel-ota-ai/market-source.json`。
- [x] 2.3 `env-check` 输出市场源配置存在性，并且不泄露私有路径。
- [x] 2.4 根部运行文档提示 systemd EnvironmentFile 应包含 `HOTEL_OTA_MARKET_SOURCE_CONFIG`。

## 3. Calendar and documentation

- [ ] 3.1 私有 calendar seed example 与校验留待后续小变更。
