## 1. 最终发送闸门

- [x] 1.1 为敏感渲染文本和 gate 替换编写失败测试。
- [x] 1.2 在 runtime payload 和插件发送前接入防御性 gate。

## 2. 渲染与路由

- [x] 2.1 清理非 debug 模板、截断提示和普通飞书内部字段泄漏。
- [x] 2.2 扩展维护/配置命令拒绝，并限制 developer debug 为本地受信 admin。

## 3. 验收

- [x] 3.1 运行普通模板禁词、renderer、router 与插件回归测试。
