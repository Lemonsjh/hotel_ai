## Why

The runtime has a V2 role-map and hotel-aware business tables, but it does not yet bind Feishu identity, chat context, approvals, configuration changes, and market-source configuration to one tenant boundary. This makes multi-owner and multi-hotel operation unsafe to extend. The Gateway also still needs a reviewed non-root migration path.

## What Changes

- Add V3 tenant-scoped role-map semantics while retaining V2 read compatibility and migration preview.
- Add Feishu card-backed configuration request, approval, audit, and price-guard policy flows. Formal price approval remains non-executing.
- Add QWeather cache semantics and a schema-validated private HTTPS event provider.
- Add a staged non-root Gateway and narrow privileged role-map apply runbook; no server state is changed by repository code.

## Capabilities

### New Capabilities
- `tenant-scoped-feishu-auth`: V3 membership, group binding, direct-message hotel selection, and cross-tenant rejection.
- `configuration-card-audit`: server-side nonces, two-person approval, append-only audit chain, and narrow apply queue.
- `tenant-price-approval`: versioned price guards and formal, non-executing price approvals.
- `verified-market-providers`: tenant-scoped QWeather and verified HTTPS event ingestion with explicit degradation.
- `gateway-nonroot-migration`: preflight, hardened unit, rollout, and rollback documentation.

### Modified Capabilities
- `feishu-ingress`: derive hotel context from trusted authorization state instead of a caller-provided hotel id.

## Impact

This change modifies runtime auth, storage, Feishu routing and plugin behavior, market source loading, deployment documentation, and tests. It does not enable a channel write, modify `/etc/hotel-ota-ai/`, restart Gateway, or install systemd units.
