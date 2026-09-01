# Feishu production output boundary

Production Feishu results may reuse the generic route scaffold internally, but demo-only provenance must not cross the final output boundary.

- Immediately before production rendering and before the route result is returned, remove only `demo_dataset_id`, `demo_business_date`, and `demo_run_id`.
- Do not rewrite business metrics, `data_source_type`, `freshness_status`, `business_result_generated`, SQL results, or skill decisions at this boundary.
- Real `data_business_date` therefore remains available to the renderer when a stale `demo_business_date` was inherited from the scaffold.
- Local CLI/test demo flows are unchanged; production Feishu still blocks explicit demo/sample/synthetic fallback according to the existing contract.
