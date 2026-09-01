# 共享 Skill 文件

这些文件供 17 个酒店 OTA skill 共同读取。

- `common-contract.md`：标准输入、输出、安全规则、运行时命令、P0/P1 优先级。
- `channel-api-map.md`：Beyondh、美团、订单来了、RPA、人工上传和样例数据的统一渠道适配映射。
- `beyondh-api-map.md`：旧文件兼容提示；新 skill 应读取 `channel-api-map.md`。
- `operating-policy.md`：角色权限、审批闸门、fallback 顺序和竞品参考边界。
- `prompts/output-template.md`：飞书和聊天回复中文模板。
