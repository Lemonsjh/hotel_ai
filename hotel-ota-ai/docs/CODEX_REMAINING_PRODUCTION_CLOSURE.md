# Codex Remaining Production Closure Checklist

This document tracks the work that still requires local/Codex execution after the safe commits already made by ChatGPT.

## Already added by ChatGPT

- `config/skill-dependencies.yaml`
- `runtime/skill_orchestrator.py`
- `tests/skills/test_skill_dependency_orchestrator.py`
- `docs/S14_EXT_HTML_REPORT_CONTRACT.md`

These are safe scaffolding changes. They do not modify the Feishu auth core.

## Must be done by Codex/local agent

## Current local verification status

Last checked locally on 2026-06-29.

- Item 1 is complete: `tests/feishu/test_dm_open_id_auth.py` no longer imports `runtime/live_contract_patch.py`, and `runtime.safety.auth` is no longer patched by `live_contract_patch` for DM open_id auth.
- Item 2 is complete under the latest production rule: router code no longer hardcodes concrete hotel alias relationships, production Feishu blocks generic `*-demo` hotel ids, and legacy demo compatibility ids are read from `examples/demo_data/demo_manifest.json`.
- Item 4 is covered for the tested S4 and revenue routes by `tests/feishu/test_no_demo_sample_fallback.py`; keep it as a regression target for new production Feishu routes.
- Item 3 is covered by the current Feishu output gate and regression tests.
- Item 5 is complete for Feishu routes 3 and 9: real routing records the required `skill_orchestrator` dependency chain for S16 and S5.
- Item 6 is complete under the current implementation: S14-EXT/N022 is served by `runtime/s14_ext_third_party_diagnosis.py`, `runtime/s14_operation_diagnosis.py`, and `runtime/reports/external_ota_html_report.py`; tests cover Excel/MySQL modes, HTML artifact metadata, N022 routing, and Feishu-safe output.
- Item 7 is complete: S16 no longer uses `occupied_rooms`, checked-out rooms, or cancelled orders as today's sold room nights; missing trusted room-night facts now returns a data-gap path.
- Item 8 is complete: Zhiting price task readback keeps plugin statuses as `PENDING/SUCCESS/FAILED` and exposes a derived review lifecycle (`queued_to_plugin`, `plugin_failed`, `verification_pending`) for business verification.
- Item 9 is complete for current chat-based operations: ROLE/BIND/CFG request, confirmation, DB write, audit, and read-model query paths are covered by runtime and Feishu tests.

### 1. Formalize Feishu DM open_id auth

Move private-chat identity resolution from `runtime/live_contract_patch.py` into the formal auth path.

Target files:

- `runtime/safety/auth.py`
- optional new helper: `runtime/safety/dm_open_id_auth.py`
- `tests/feishu/test_dm_open_id_auth.py`

Requirements:

- `tests/feishu/test_dm_open_id_auth.py` must not import `runtime/live_contract_patch.py`.
- Private chat with `chat_id=user:*` must use `open_id/user_id/union_id -> auth_principals -> hotel_memberships`.
- Missing private chat id with a single hotel membership resolves that hotel.
- Group chat must still fail closed if it has no trusted business chat id.

Validation:

```bash
python -m unittest tests.feishu.test_dm_open_id_auth
python -m unittest tests.feishu.test_no_demo_sample_fallback
python -m unittest discover tests
```

### 2. Move alias and demo-hotel logic out of live_contract_patch

Target file:

- `runtime/feishu_command_router.py`

Requirements:

- Do not hardcode any concrete hotel alias relationships in runtime code.
- Hotel alias resolution must come from a future private tenant alias resolver or registry, not from router constants.
- Generic `*-demo` hotel ids are demo hotel ids and must be blocked in production Feishu.
- Do not depend on `_patch_router` for this behavior.

### 3. Harden final Feishu output gate

Target files:

- `runtime/feishu_output_renderer.py` or new `runtime/feishu_output_gate.py`
- `runtime/feishu_command_router.py`

Requirements:

- All final `send_payload` objects must be sanitized before sending.
- Redact identity markers, internal paths, runtime file/line references, model/provider footers, DSN, token, secret, password.

### 4. Disable demo/sample/synthetic in production Feishu

Production Feishu must not fall back to demo data. Missing data returns `data_gap`.

### 5. Wire skill orchestrator into real routing

Use the added `runtime/skill_orchestrator.py` and `config/skill-dependencies.yaml`.

Required flows:

- Progress deviation runs S2 and S15 first.
- Revenue decision runs S2, S4, S15, S16, and OTA price mapping first.
- Target skill does not run if an upstream dependency returns a blocking status.

### 6. Implement S14-EXT HTML report runtime

Follow `docs/S14_EXT_HTML_REPORT_CONTRACT.md`.

Current implementation files:

- `runtime/s14_ext_third_party_diagnosis.py`
- `runtime/s14_operation_diagnosis.py`
- `runtime/reports/external_ota_html_report.py`

### 7. Fix today sales metric contract

Do not mix checked-out rooms/current occupied rooms/cancelled orders into today's sold room nights.

### 8. Add price task review and plugin verification

Implement task status transitions:

```text
created -> pending_review -> approved -> queued_to_plugin -> plugin_picked -> plugin_success/plugin_failed -> verification_pending -> verified_success/verified_mismatch
```

### 9. Make ROLE/BIND/CFG executable and queryable

Ensure request + confirm writes DB and is immediately queryable.

## Final validation

```bash
python -m unittest tests.feishu.test_dm_open_id_auth
python -m unittest tests.feishu.test_no_demo_sample_fallback
python -m unittest tests.skills.test_skill_dependency_orchestrator
python -m unittest discover tests
```
