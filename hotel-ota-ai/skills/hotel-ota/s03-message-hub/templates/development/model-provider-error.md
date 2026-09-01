# 模型服务异常模板

结论：当前是模型服务或 provider 配额异常。
证据：当前请求命中 `{{blocked_reason}}`。
建议：检查模型供应商 API Key、余额、配额、模型名和流式兼容性。
风险：不要误判为业务 API 或 runtime 数据故障。
