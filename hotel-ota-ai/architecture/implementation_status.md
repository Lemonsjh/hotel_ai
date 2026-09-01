## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

# V20 Implementation Status

Implemented in this workspace:

- A0-A6, N001-N022, E001-E067, SC01-SC10 registries.
- Field, node IO, source mapping, contract version, and field status policy.
- Runtime DemoMode, DataGate, approval guard, field loader, field coverage.
- Full-chain demo fixtures for SC01-SC10 and node-level demo fixtures for N001-N022.
- Skill V20 alignment references for S1-S17 and S14-EXT.
- S14-EXT extension skill for third-party OTA diagnosis HTML preview.
- Ops guides for private config, demo mode, server update, backup, and rollback.

Still intentionally not done:

- Production server update.
- Production private config changes.
- Final BP threshold tuning beyond draft algorithm rule placement.
- Deleting or moving legacy OpenClaw entry files.

## Phase 7 And Phase 9 Completion

- Phase 7 is implemented through `architecture/phase7_skill_algorithm_completion.*`, per-skill `runtime/algorithm_rules/*.yaml`, and each skill's `references/v20_behavior_cases.json`.
- Phase 9 is implemented through `architecture/phase9_document_convergence*` and `requirements/V20文档收敛索引.md`; old documents are retained but marked registry-first.