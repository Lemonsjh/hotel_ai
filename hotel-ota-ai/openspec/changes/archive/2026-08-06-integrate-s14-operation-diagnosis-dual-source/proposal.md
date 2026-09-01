## Why

The S14 collaboration package contains useful calculator, Excel reader, MySQL reader, field mapping, and HTML report ideas. It also contains a full legacy project, `.git`, `.venv`, fixed public HTTP paths, historical report outputs, and an independent Feishu sender. Those artifacts must not be copied into the V27 workspace.

The project now needs two separate S14 paths:

- `S14 / N009`: current-hotel OTA operation diagnosis inside the normal hotel chain.
- `S14-EXT / N022`: isolated third-party OTA diagnosis report preview.

## What Changes

- Keep current-hotel `S14` mapped to `N009`.
- Add/keep isolated `S14-EXT` mapped to `N022`.
- Extract only safe scoring, Excel/MySQL normalization, and report-rendering ideas from the external collaboration package `s14-feishu-test.zip`.
- Route `demo-node N022`, SC10, and third-party report preview through `runtime/s14_ext_third_party_diagnosis.py`.
- Keep `s14-diagnosis` for current-hotel S14 dual-source diagnosis.
- Add `s14-ext-diagnosis` for isolated third-party report preview and trusted local Excel/MySQL maintenance flows.

## Impact

- No legacy `.git`, `.venv`, public reports, customer samples, hard-coded DSN, or old Feishu sending logic enters the project.
- S14-EXT does not create formal approvals or live actions.
- Public `report_url` stays `null` unless a separate HTTPS publisher is configured and verified.
- Feishu business output never exposes local report paths.
