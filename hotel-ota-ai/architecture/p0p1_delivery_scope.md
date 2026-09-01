## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

# P0/P1 Delivery Scope

This file fixes the P0/P1 boundary for V20 alignment.

- P0/P1 must cover A0 entry/security/data-gate, A1 S2/S4 data inputs, A2 S14/S15/S16 diagnostics and targets, A3 S5 strategy, A4 S6 execution guard, and A5 S3 messages.
- P2 keeps S7/S8/S9/S10/S11/S12/S13/S17 and A6 deep evolution available but non-blocking.
- N022/S14-EXT is registered as P0/P2: demo/report preview can be delivered early, production external report workflow stays gated.
- SC01-SC10 are the registered scenarios. SC11-SC12 are not invented unless a newer registry provides them.
- Demo Mode can cover all scenarios, but every demo output is `demo_data` and cannot create formal approval or live execution.