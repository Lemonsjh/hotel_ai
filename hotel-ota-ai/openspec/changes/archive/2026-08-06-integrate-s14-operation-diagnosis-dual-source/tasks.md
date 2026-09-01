## 1. Package Extraction And Canonical Facts

- [x] 1.1 Add tests for Excel/MySQL normalization to canonical S14 facts.
- [x] 1.2 Extract only safe calculator, mapping, reader, and template ideas from the external collaboration package `s14-feishu-test.zip`.
- [x] 1.3 Keep current-hotel S14 on `N009/S14`.

## 2. S14-EXT Isolation

- [x] 2.1 Add an isolated S14-EXT runtime module for `N022/S14-EXT`.
- [x] 2.2 Route `demo-node N022`, SC10, and third-party report preview through the isolated S14-EXT module.
- [x] 2.3 Add `s14-ext-diagnosis` CLI while keeping `s14-diagnosis` for current-hotel S14.
- [x] 2.4 Strip local HTML paths from Feishu output and expose only safe artifact metadata.

## 3. Verification

- [x] 3.1 Add regression tests for `N009/S14` and `N022/S14-EXT` identity separation.
- [x] 3.2 Add regression tests that production Feishu third-party preview is isolated and not hotel-auth-bound.
- [x] 3.3 Keep S14/S14-EXT read-only with `formal_approval_created=false` and `live_execution_count=0`.
