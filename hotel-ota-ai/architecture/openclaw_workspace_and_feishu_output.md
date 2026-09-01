## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

# OpenClaw Workspace And Feishu Output

## OpenClaw Workspace Initialization Files

`USER.md`, `IDENTITY.md`, `SOUL.md`, `HEARTBEAT.md`, and `MEMORY.md` are tracked project files. They carry high-priority workspace rules for project identity, boundaries, current safety posture, and long-term memory summary.

They are not permission sources, business data sources, or approval evidence. Permission still comes from the private Feishu role map and `runtime/safety/auth.py`; field facts come from `contracts/`; execution boundaries come from `runtime/`.

## Feishu Output Profiles

Runtime results must remain complete internally. Feishu-facing responses are rendered by `runtime/feishu_output_renderer.py` according to `output_profile`.

Default profile mapping:

- `admin` and `owner`: `owner_business`
- `operator`: `operator_workbench`
- `frontdesk`: `frontdesk_task`
- `guest`: `guest_limited`

Business users do not see internal fields such as `run_id`, `node_id`, `skill_id`, `scenario_id`, fixture path, raw JSON, Model, or Provider. Only `developer_debug` shows runtime metadata. Output detail is not execution permission; permission and live execution still belong to runtime gates.

## Runtime-Backed Feishu Routing

Feishu natural language requests should follow this path:

```text
Feishu natural language command
  -> runtime/feishu_command_router.py
  -> structured runtime result
  -> runtime/feishu_output_renderer.py
  -> output_profile-specific Feishu response
```

Do not claim that a full-chain result was reused from memory unless a real run cache exists and reports `run_id`, cache source, generation time, and validation status.

## Unified Demo Facts

`examples/demo_data/demo_manifest.json` is the entry point for demo facts. N001-N022, SC01-SC10, S02, S05, S6, S3 preview, and N022 report preview must read from the same demo fact set.

`seed-demo` writes this fact set into SQLite. `demo_data` does not represent real today business results, cannot create formal approvals, and cannot enter live execution.

## Current Agent Implementation

The current implementation is one OpenClaw chief agent plus A0-A6 logical Agent layers. It is not seven independent Agent runtime instances. Agent IDs must come from `architecture/node_agent_mapping.json`, loaded by `runtime/agent_mapping_loader.py`.
