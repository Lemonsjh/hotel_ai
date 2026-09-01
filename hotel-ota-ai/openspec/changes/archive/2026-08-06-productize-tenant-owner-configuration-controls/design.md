## Context

The prior control plane correctly requires two distinct global admins for sensitive role changes and two in-scope approvers for price policies. That rule is too restrictive for a hotel Owner assigning ordinary operating roles, while a single absolute price-change cap cannot represent the intended directional business guardrails.

## Decisions

- The Owner exception applies only to a V3 hotel membership request for another existing principal in the Owner's hotel and only to `operator` or `frontdesk`. The same Owner may create and confirm that request. It never applies to self-targeting, cross-hotel changes, `owner`, `admin`, or global changes.
- Global admins retain the distinct-approver rule for Owner/global scope changes. Gateway only places an approved role request in the existing apply queue; it never mutates `/etc`.
- New price policies require `max_increase_pct`, `max_decrease_pct`, `min_increase_pct`, and `min_decrease_pct`. A legacy stored single cap maps to both maxima with zero minima during read. New writes do not accept the legacy field alone.
- Directional checks use the signed change from trusted old price. A no-change request is rejected as `no_effective_change`. Approval hashes contain all directional thresholds, floor/ceiling, hotel, room type, policy id/version, and old price.
- Feishu management remains read-only. It exposes tenant-scoped summaries, not identities, paths, raw configuration, or policy internals to unprivileged roles. Existing sealed card request/callback primitives are reused without guessing the native Feishu event format.

## Risks and Mitigations

- Owner self-confirmation could broaden access if scope validation is weak. The request and confirmation both independently validate the actor hotel membership, target, role, and operation.
- Legacy policies can remain in SQLite. Read normalization keeps them valid while all new policy requests require the four fields.
- Management status can leak control-plane details. The read model returns counts, versions, room identifiers, and redacted states only after V3 hotel scope authorization.
