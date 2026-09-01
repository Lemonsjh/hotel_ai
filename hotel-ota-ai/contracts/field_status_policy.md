# Field Status Policy

- `confirmed`: verified by the algorithm source or a confirmed external source.
- `algorithm_required`: required by blueprint logic even if no current API exposes it yet.
- `candidate`: useful but not confirmed; may be used for diagnosis or demo only.
- `manual_required`: must be supplied or audited manually before production use.
- `deprecated`: retained for compatibility, not for new algorithm decisions.
- `inferred` and `unavailable` remain compatibility states from the current project and map to `candidate` / `manual_required` when loaded.

Demo data is never `confirmed` production evidence. It must remain blocked from formal approval and live execution.
