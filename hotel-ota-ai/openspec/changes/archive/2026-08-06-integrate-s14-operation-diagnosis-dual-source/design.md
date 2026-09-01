## Decisions

- `runtime/s14_operation_diagnosis.py` is the current-hotel S14 adapter and reports `node_id=N009`, `skill_id=S14`.
- `runtime/s14_ext_third_party_diagnosis.py` is the isolated third-party adapter and reports `node_id=N022`, `skill_id=S14-EXT`.
- Excel and MySQL inputs first normalize to canonical aggregate facts before scoring. Free-form chat metrics, upstream skill output, raw JSON, and arbitrary Feishu file paths are rejected.
- S14-EXT can generate a local HTML preview artifact, but compact Feishu output strips local paths and exposes only report metadata.
- `s14-diagnosis` remains for current-hotel S14 trusted maintenance use. `s14-ext-diagnosis` is the S14-EXT trusted maintenance/demo command.
- Production Feishu hotel-auth is still required for current-hotel business data. Isolated S14-EXT preview may return structure/demo preview without hotel tenant auth because it is not a current-hotel fact path.

## Safety

- Both S14 and S14-EXT remain read-only.
- S14-EXT output is preview-only and cannot become approval data or live execution data.
- If fields are missing, output `partial` or `data_gap`; never invent diagnosis facts.
- No report publisher is considered enabled until HTTPS base URL and retention controls are explicitly configured and tested.
