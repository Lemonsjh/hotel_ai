# MEMORY

## 当前运行补充

长期记忆不能替代 SQLite Active Auth、normalized query layer 或 V27 contract。权限先查 SQLite active tables；JSON 只作 bootstrap / emergency fallback。S15 小时目标曲线的来源和置信度必须来自 runtime 输出，不得由记忆补造。

本文件记录长期项目记忆的使用边界。它不是权限来源、业务数据来源或审批依据。

## 可记忆内容

长期记忆只记录稳定结构、规则入口和脱敏协作结论。它可以帮助解释项目背景，但不能替代 runtime、字段契约、角色校验或审批校验。

可作为长期背景的入口：

- V27 工程契约：`contracts/v27/contract.json` 与 `contracts/v27/`。
- Agent 注册表：`architecture/agent_registry.json`。
- 节点到 Agent 映射：`architecture/node_agent_mapping.json`。
- 场景链路：`architecture/scenario_chain_registry.json`。
- Skill 规则：`skills/hotel-ota/*/references/`。
- Runtime 执行：`runtime/`。
- 部署包边界：`manifests/deploy_manifest.yaml`。
- 飞书命令路由：`runtime/feishu_command_router.py`。
- 飞书输出渲染：`runtime/feishu_output_renderer.py`。

## 禁止记忆内容

不得保存或召回：

- 真实飞书身份标识。
- 客户隐私。
- 审批凭证。
- 接口凭据。
- 数据库连接串。
- 行级订单。
- 私有配置路径和值。
- `product_cipher` 明文。

## 使用边界

- 当前经营事实必须重新走 runtime 或受控数据源。
- 当前权限、酒店范围和角色必须重新走 runtime 权限链路。
- demo 问题必须说明数据来源和 fallback 状态。
- 记忆不能编造节假日、活动、经营数据或审批结果。
- 记忆不能替代 DataGate、approval guard、live switch 或输出安全闸门。
