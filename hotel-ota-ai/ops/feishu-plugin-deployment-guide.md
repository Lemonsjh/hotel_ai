# Feishu Plugin Deployment Guide

## Boundary

This guide installs only the repository plugin and validates runtime routing. It never copies a private role map, database mapping, token, app secret, or environment file into Git.

## 1. Preflight

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
git status --short
python -m unittest discover tests
node --test ops/openclaw-plugins/hotel-ota-feishu-auth/test/auth_ingress.test.mjs
openclaw config validate
```

Stop if the server worktree has unreviewed changes or any validation fails. Keep a timestamped copy of `/root/.openclaw/openclaw.json` and the metadata of `/etc/hotel-ota-ai/`; do not copy private file contents into the workspace.

## 2. Configure the plugin environment

In `/etc/hotel-ota-ai/hotel-ota.env`, set only the two Feishu account names bound to `hotel-ota-chief`:

```bash
HOTEL_OTA_FEISHU_AUTH_ACCOUNTS='account-one,account-two'
HOTEL_OTA_RUNTIME_ENTRY='/opt/openclaw/workspaces/hotel-ota-ai/runtime/hotel_ota_runtime.py'
HOTEL_OTA_AUTH_CONFIG='/etc/hotel-ota-ai/feishu-role-map.json'
HOTEL_OTA_DB='/var/lib/hotel-ota-ai/hotel_ops.sqlite'
HOTEL_OTA_FEISHU_PLUGIN_DIAGNOSTICS='1'
```

Do not use account IDs from another Agent, and do not set a caller-supplied role variable. Keep permissions restrictive:

```bash
chmod 600 /etc/hotel-ota-ai/hotel-ota.env /etc/hotel-ota-ai/feishu-role-map.json
```

## 3. Enable and validate

Apply the repository's object-level OpenClaw patch with dry-run first. It must retain existing agents, Feishu bindings, channels and model credentials, and use `contextInjection=continuation-skip`.

```bash
openclaw config patch --file ops/openclaw-hotel-ota-production.patch.json5 --dry-run
openclaw config patch --file ops/openclaw-hotel-ota-production.patch.json5
openclaw config validate
openclaw plugins inspect hotel-ota-feishu-auth --runtime --json
sudo bash ops/check-gateway-feishu-plugin-env.sh
```

The inspection must report `status=loaded`, no diagnostics and one `inbound_claim` hook. The environment check must report exactly two accounts and a matching binding set without printing account names.

## 3.1 Bootstrap active authorization once

The private JSON role map is bootstrap/emergency input only. Import it into the runtime SQLite database before enabling production message claims. This command reads JSON and writes the configured SQLite database; it never rewrites `/etc/hotel-ota-ai/feishu-role-map.json`.

```bash
python runtime/hotel_ota_runtime.py --db /var/lib/hotel-ota-ai/hotel_ops.sqlite \
  auth-bootstrap-sync --auth-config /etc/hotel-ota-ai/feishu-role-map.json
```

After this succeeds, normal owner/operator/frontdesk authorization comes from SQLite. If SQLite active auth is unavailable, ordinary users are denied. A JSON global admin may only use emergency read-only status/diagnostic paths; it cannot confirm configuration, manage roles, approve, or execute live actions.

Daily member changes must use the in-chat `ROLE-...` confirmation flow. Do not hand-edit the JSON file for ordinary membership changes and do not restart Gateway after a successful SQLite role update.

## 4. Controlled restart and smoke test

Only during a maintenance window:

```bash
systemctl restart openclaw-gateway.service
systemctl status openclaw-gateway.service --no-pager
journalctl -u openclaw-gateway.service -n 200 --no-pager
```

Send one authorized message in a bound hotel group and one message from an unknown user or unbound group. Expected behavior: both messages are handled by the plugin; only the authorized message invokes `feishu-route --production-feishu`; neither log nor reply exposes identity values, paths, model/provider, raw JSON or secrets.

If logs still show `dispatching to agent` before a plugin claim, do not open channel allowlists. Run the environment check, inspect plugin diagnostics, and roll back by disabling the plugin:

```bash
openclaw plugins disable hotel-ota-feishu-auth
systemctl restart openclaw-gateway.service
```

## 5. Post-deployment checks

```bash
python runtime/hotel_ota_runtime.py role-map-preview --auth-config /etc/hotel-ota-ai/feishu-role-map.json
python runtime/hotel_ota_runtime.py env-check
openclaw security audit --deep
```

Keep `dmPolicy` and `allowFrom` unchanged until real plugin claims, V3 role-map authorization and reject-path tests all pass in production.
