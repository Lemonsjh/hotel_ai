## 1. OpenSpec and baseline

- [x] 1.1 Validate this change strictly before runtime edits.
- [x] 1.2 Record focused baseline test results without reverting existing work.

## 2. Owner hotel membership control

- [x] 2.1 Add failing tests for allowed Owner operator/frontdesk grant/revoke self-confirmation and all denied scopes.
- [x] 2.2 Implement V3 existing-principal validation, Owner scope checks, and queue behavior.

## 3. Directional price guards

- [x] 3.1 Add failing tests for legacy reads, four-field new writes, directional minimum/maximum checks, and no-effect changes.
- [x] 3.2 Migrate SQLite policy schema and control-plane, S5/S6, and hash handoff consumers.

## 4. Feishu management read model

- [x] 4.1 Add failing tests for protected tenant-scoped management intents and redacted output.
- [x] 4.2 Implement read-only route, templates, and sealed card preview contract reuse without native callback transport.

## 5. Documentation and verification

- [x] 5.1 Update V3 migration, legacy price migration, plugin registry, and non-root guidance.
- [x] 5.2 Update repository document inventory and run OpenSpec, focused, full, plugin, and diff verification.
