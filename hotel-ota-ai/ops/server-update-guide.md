# Server Update Guide

## Default Deployment Path

The default deployment supports gateway and on-demand Feishu business routing.
It does not install an S2 timer, create `hotel-ota-cron.env`, or require a
scheduled S2 push.

1. Confirm the workspace and make a directory backup before updating.
2. Keep `/etc/hotel-ota-ai/` separate from Git. Never overwrite it and never
   commit role maps, Feishu account IDs, tokens, secrets, DSNs, or database
   mappings.
3. Run repository verification before any gateway reload:

   ```bash
   cd /opt/openclaw/workspaces/hotel-ota-ai
   python tools/validate_v27_contract.py
   python tools/audit_v27_contract_drift.py
   PYTHONPYCACHEPREFIX=/tmp/hotel-ota-pycache python -m compileall runtime
   python -m unittest discover tests
   ```

4. Apply `ops/openclaw-hotel-ota-production.patch.json5` only through the
   installed OpenClaw version's supported patch workflow. Run its help and
   dry-run command first. The patch only adjusts object-level context and skill
   limits; it never replaces Agent lists, Feishu bindings, channels, models, or
   private configuration.
5. Verify the effective template values are `contextInjection=continuation-skip`,
   `bootstrapTotalMaxChars=80000`, and `maxSkillsPromptChars=16000`.
6. Verify an authorized Feishu request and a rejected request using real identity
   context. Normal output must be compact, runtime-backed, and free of internal
   JSON, identity values, model details, and server paths.

## Tenant Role Map And Administrative Cards

Use the V3 role-map layout from `config/feishu-role-map.example.json` for new
multi-hotel deployments. It separates globally unique principals, global
admins, hotel memberships, and group-chat-to-hotel bindings. Do not overwrite
an existing private V1/V2 map automatically: first run the repository's
read-only migration preview, validate a private V3 candidate, then switch it
in a maintenance window.

Business chat free text cannot change roles, guards, environment values, or
private files. The control-plane runtime supports a sealed administrative card
contract with a request id, nonce, expiry, and payload hash. Before enabling a
provider callback, validate the exact Feishu/OpenClaw callback event contract
in an isolated home. The callback must reauthenticate the actor, check hotel
scope, reject replay/self approval/tampering, and only queue a role-map apply.
It must never give the Gateway write access to `/etc/hotel-ota-ai/`.

Approved role changes stay in the local apply queue. A separately reviewed,
root-owned helper may validate an allowlisted V3 candidate and atomically
replace the private role-map. The helper contract is documented in
`ops/role-map-apply-helper.md`; it is not run by the Gateway or by this
repository update procedure.

An Owner may create and once confirm a grant or revoke for another existing
`operator` or `frontdesk` principal in that Owner's own hotel. An Owner cannot
target self, another Owner, an admin, or a different hotel. Owner/global scope
changes still require two distinct global administrators. The request only
enters the apply queue; it does not update the private role-map in place.

New price-guard policies use `max_increase_pct`, `max_decrease_pct`,
`min_increase_pct`, and `min_decrease_pct`. Existing stored
`max_single_change_pct` policies remain readable as both maxima with zero
minima, but new policy requests must provide all four values. Formal price
approvals bind the hotel, room type, old price, floor/ceiling, all four limits,
active guard policy id/version, and execution payload hash. Approval only
changes state; OTA/PMS live writes remain disabled.

Feishu management text is read-only: authorized Owner/admin users may request
member role status, price guard status, pending configuration requests, or an
audit summary. It never applies a change. The sealed card backend remains
transport-neutral until a redacted real Feishu callback event has been verified
in isolated staging.

## Tenant Market Providers

Configure weather, events, and regional heat under
`hotels.<hotel_id>` in the private market-source JSON. QWeather requests time
out after five seconds and cache validated responses for fifteen minutes. The
optional event HTTP provider requires HTTPS, a bearer token supplied by an
environment variable, source metadata, and a valid event schema; fresh events
cache for up to six hours. Provider timeouts with an expired cache produce a
stale `partial` result, never a fresh claim. A missing tenant configuration
must not fall back to another hotel's provider settings.

The repository example contains no credentials, endpoint, or real location.
Keep all real values in `/etc/hotel-ota-ai/` or the service environment, with
root ownership and a read-only runtime group.

## Gateway Non-Root Migration (Human-Approved)

This is a production maintenance action, not a default repository update.
Before changing the unit, back up the effective unit (`systemctl cat`), the
workspace, and private configuration metadata. Review
`ops/systemd/openclaw-gateway-nonroot.override.conf.example`, then run:

```bash
ops/gateway-nonroot-preflight.sh --dry-run
systemd-analyze verify /etc/systemd/system/openclaw-gateway.service
```

The template uses `User=openclaw`, `NoNewPrivileges=true`,
`ProtectSystem=strict`, a read-only `/etc/hotel-ota-ai`, and explicit writable
data/log directories. Copying a drop-in, reloading systemd, or restarting the
Gateway requires separate human approval. On failure, restore the backed-up
unit/drop-in and original ownership; do not use `git reset --hard` or overwrite
private configuration.

## Scheduled S2 Messages

Scheduled S2 delivery is disabled by default and has no replacement timer.
The former model-driven OpenClaw S2 job may be stopped after confirming it is
the known failed job:

```bash
openclaw cron list
openclaw cron disable 7de406f5-e7e7-4fac-95bb-725e90898f54
systemctl list-timers 'hotel-ota-s2-snapshot*' --all
```

Do not install `hotel-ota-s2-snapshot.service`,
`hotel-ota-s2-snapshot.timer`, or `/etc/hotel-ota-ai/hotel-ota-cron.env`.
On-demand Feishu routing remains available without them.

## Staged Inbound Authorization Plugin

`ops/openclaw-plugins/hotel-ota-feishu-auth/` is an independent model-before
authorization hardening measure. It can claim authorized hotel Feishu messages
before a model turn, but it does not depend on any S2 timer. First run its
isolated-home install, `config validate`, runtime inspection, and inbound claim
smoke test. Only then may an operator explicitly enable it in production; keep
the existing gateway configuration and Feishu bindings unchanged until those
checks pass.

## Time-Aware Runtime Smoke Tests

Use actual Feishu identity values privately. The following commands are shape
examples only and must not be copied with placeholder credentials into Git:

```bash
python runtime/hotel_ota_runtime.py feishu-route \
  --message '16:40 进度诊断' --production-feishu --render \
  --open-id '<sender_open_id>' --chat-id '<chat_id>' \
  --auth-config /etc/hotel-ota-ai/feishu-role-map.json

python runtime/hotel_ota_runtime.py feishu-route \
  --message '18:20 收益决策' --production-feishu --render \
  --open-id '<sender_open_id>' --chat-id '<chat_id>' \
  --auth-config /etc/hotel-ota-ai/feishu-role-map.json
```

Both results must use their supplied checkpoint time. Demo and synthetic data
remain preview-only: no formal approval creation and no live execution.
