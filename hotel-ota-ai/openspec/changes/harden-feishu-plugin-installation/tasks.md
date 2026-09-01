## 1. 插件交付

- [x] 1.1 依据 OpenClaw 2026.5.28 包内 schema 新增 `openclaw.plugin.json`。
- [x] 1.2 为 manifest、账号筛选、claim 和拒绝发送补充 Node 测试。

## 2. 安装验证

- [x] 2.1 新增隔离 OpenClaw Home 的 install、validate、runtime inspection smoke 脚本和说明。
- [x] 2.2 更新部署说明，明确插件与 S2 timer 无依赖关系。

## 3. 发布前人工操作

- [ ] 3.1 在目标服务器实际执行隔离 OpenClaw Home install/validate/inbound_claim smoke。
- [ ] 3.2 盘点生产 registry 后，由人工确认启用插件和两个酒店账号 claim。
