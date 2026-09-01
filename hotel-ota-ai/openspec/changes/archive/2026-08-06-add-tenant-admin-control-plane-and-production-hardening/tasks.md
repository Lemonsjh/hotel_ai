## 1. OpenSpec and baseline

- [x] 1.1 Validate this change strictly before runtime edits.
- [x] 1.2 Record the current dirty-tree boundary and run focused baseline tests without reverting existing work.

## 2. Tenant authorization

- [x] 2.1 Add failing V3 role-map, membership, group-binding, direct-message selection, and V2 compatibility tests.
- [x] 2.2 Implement V3 parsing, validation, migration preview, tenant resolution, and fail-closed route enforcement.
- [x] 2.3 Extend inbound plugin authorization with the same V3 tenant semantics.

## 3. Configuration cards and audit

- [x] 3.1 Add failing tests for nonce expiry, replay, tampering, self-approval, cross-tenant rejection, and audit-chain validation.
- [x] 3.2 Add control-plane storage, configuration request state machine, audit events, and a platform-neutral sealed card callback contract. Production Feishu callback binding remains staging-only until its exact platform event shape is verified.
- [x] 3.3 Add the privileged apply queue and non-executing, documented helper contract without invoking it.

## 4. Price guard and formal approval

- [x] 4.1 Add failing tests for versioned hotel/room price guards and formal approval binding.
- [x] 4.2 Implement price guard policy storage, approval creation/approval state, and S5 handoff binding while retaining live disabled.

## 5. Market providers

- [x] 5.1 Add failing tests for cache TTL, HTTPS-only activity sources, missing bearer credentials, invalid schemas, and stale degradation.
- [x] 5.2 Implement tenant-scoped QWeather cache and verified HTTP activity provider.

## 6. Gateway hardening and documentation

- [x] 6.1 Add static preflight and deployment-boundary tests for non-root hardening assets.
- [x] 6.2 Add systemd templates, preflight, rollback runbook, and private-file permission guidance without server mutation.

## 7. Verification

- [x] 7.1 Run OpenSpec, contract, drift, Python, plugin Node, diff, and deployment-boundary checks.
- [x] 7.2 Review changed-file scope and document the remaining human-only server cutover steps.
