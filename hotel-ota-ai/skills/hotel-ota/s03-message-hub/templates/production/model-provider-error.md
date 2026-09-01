# 模型服务异常模板

结论：当前是模型服务或 provider 配额异常，不是酒店业务 API 结论。
证据：当前请求命中 `{{blocked_reason}}`。
建议：请管理员检查模型供应商 API Key、余额、配额或兼容性；业务数据源状态需另行用 runtime 检查。
风险：不要把模型 provider billing/quota 错误误判为美团、PMS 或数据库异常。
