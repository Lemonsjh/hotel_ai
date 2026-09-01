# Route Tests

Route tests must assert these invariants:

- Every intent case resolves to one registered SC01-SC10 route.
- Every route only references nodes from `architecture/node_registry.json`.
- Default routes use registered required edges only.
- Optional edges require an explicit branch condition.
- Demo routes may run preview/dry-run outputs, but cannot create formal approvals or live writes.
