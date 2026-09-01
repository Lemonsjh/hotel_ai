## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

# Redundancy, Conflict, and Missing Audit

## Current resolution

- README/AGENTS/BOOTSTRAP/TOOLS remain OpenClaw-readable entry points.
- Architecture facts moved to `architecture/` registries.
- Field facts moved to `contracts/`.
- Skill alignment moved to each skill's `references/v27_alignment.json`.
- Runtime safety remains the executable source for auth, approval, DataGate, freshness, and demo/live blocking.

## Not deleted

No old skill, old document, or OpenClaw path is deleted. Legacy prose should be treated as compatibility context when it conflicts with the registries.

## Known deferred work

Deep BP formula finalization remains a follow-up after business threshold confirmation. The current implementation fixes placement, safety, coverage reporting, demo mode, and machine-readable routing.
