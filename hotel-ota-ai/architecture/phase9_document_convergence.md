## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 和 runtime 实际返回为工程事实源。V26 及更早资料仅作为历史迁移背景；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

# Phase 9 Document Convergence

## 当前结论

- `README.md`、`AGENTS.md`、`BOOTSTRAP.md` 和 `TOOLS.md` 保持为 OpenClaw 根级入口。
- `contracts/v27/`、runtime、`architecture/`、`router/` 和各 Skill 的 V27 references 是当前实现与行为依据。
- 服务器更新与部署统一由 `ops/server-update-guide.md`、`manifests/deploy_manifest.yaml` 和实际运行验证命令说明。
- 旧 `requirements/` 文档不再参与运行、部署、测试、授权、审批或业务事实判断。

## 2026-08-07 旧 requirements 清理

用户已明确授权删除旧 `requirements/` 文件。完成的收敛动作：

- 删除 `requirements/` 下全部 25 个历史教程、提示词、P0/P1 清单、旧字段规则、旧契约和验收资料。
- 删除仅用于维持旧文件存在的 `architecture/phase9_document_convergence_index.json`。
- 将 README 的部署入口迁移到当前 `ops/` 与 `manifests/` 事实源。
- 将文档上下文清单改为规则化的 V2 清单，不再枚举和保留已删除的 legacy requirements 路径。
- 修改聚焦测试，反向约束旧目录、旧索引和旧引用不得重新引入。

本次清理不修改 runtime 业务逻辑、数据库契约、S1-S17 算法、飞书权限或生产配置。
