# V26 Skill Alignment Policy

Each skill keeps its original OpenClaw entry files. V26 alignment is added as the current reference layer:

- `references/v26_alignment.json` binds the skill to one node, one Agent, upstream/downstream edges, scenario coverage, demo fixture, algorithm rules, and forbidden actions.
- Field facts must be read from `contracts/v26/field_registry.yaml` and `contracts/v26/node_io_contract.yaml`.
- Demo data can only produce preview, dry-run, simulation, message preview, or report preview results.
- Demo, sample, stale, and missing-date payloads must not create formal approval or live execution.

