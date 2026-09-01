## Context

Existing runtime records already carry `hotel_id`, while V2 role-map authorization is global. The correct extension is a control plane where trusted identity resolves a tenant before any business route, approval, configuration request, or market read. Feishu is the first management surface; there is no Web console in this change.

## Goals / Non-Goals

**Goals:** tenant-scoped identity and access, constrained Feishu management cards, immutable audit records, versioned price guards, formal price approvals without execution, verified market reads, and a deployable non-root Gateway migration.

**Non-Goals:** OTA/PMS live writes, arbitrary natural-language configuration mutation, browser administration UI, automatic `/etc` mutation, automatic service reload, or a new S2 timer.

## Decisions

- V3 role-map separates globally unique users, global admins, hotel memberships, group-chat-to-hotel bindings, and direct-message policy. A group may bind to exactly one hotel. A direct message must select one hotel from the caller's memberships.
- V2 remains read-compatible. Migration is preview-only until an operator manually deploys a validated V3 private file.
- Every card callback uses an opaque server-side request id, nonce, expiry, authenticated identity, tenant scope, request state, and canonical payload hash. Callbacks never trust card-supplied price, role, hotel, or identity values.
- Role changes require two distinct global admins. Price guard policy changes require two distinct in-scope owner/admin identities. Formal price approvals require fresh/current data and an in-scope approver distinct from the requester, but never invoke a channel adapter.
- Audit events are insert-only through runtime APIs and form a per-tenant hash chain. Feishu presents summaries and audit ids only.
- Role-map application is queued after approval and executed only by a separately documented, root-owned helper that validates an allowlisted V3 document before atomic replacement. Gateway receives no `/etc` write permission.
- QWeather results cache for 15 minutes. The verified activity provider requires HTTPS, a bearer token from an environment variable, provider/source id, fetched timestamp, event id, event date, confidence, and source URL; cached events expire after six hours. Missing or stale components produce `partial` or `data_gap`.
- Gateway migration runs the service as `openclaw` with a dedicated group, `NoNewPrivileges=true`, `ProtectSystem=strict`, `UMask=027`, no ambient capabilities, and explicit read/write paths. The final server cutover remains a human-approved maintenance action.

## Risks / Trade-offs

- A V3 role-map with no valid membership blocks protected requests by design; rollout starts with migration preview and staging smoke tests.
- Two-person controls can delay small configuration changes; this is intentional for access and price guard mutation.
- Gateway hardening can expose undeclared file dependencies; preflight fails before any cutover and rollback restores the previous unit and ownership.
