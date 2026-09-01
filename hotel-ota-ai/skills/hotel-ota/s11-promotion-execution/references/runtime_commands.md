# S11 runtime commands

## Primary semantics

`promotion-suggestion` is the conceptual S11 command: read S8/S9/S10/S16 deterministic results and return a read-only `PromotionPlan`.

## Compatibility

`promotion-execute` is a historical command name only. It MUST have exactly the same read-only S11 suggestion semantics. It must never create a task, request approval, dispatch work, call an OTA write API, or modify promotion state.

`promotion-plan` remains the historical S8 display alias. It is not S11 and must continue to return S8 promotion-display facts only.

## Forbidden command semantics

There is no S11 live mode, approval mode, confirmation command, task mode, dispatch mode, or execution/readback mode.
