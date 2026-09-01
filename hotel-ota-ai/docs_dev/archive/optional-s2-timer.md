# Archived S2 Timer Prototype

The model-free S2 timer prototype was removed from the active deployment path
on 2026-06-22. It is not required for the gateway, inbound authorization, or
on-demand Feishu business routes.

Do not install `hotel-ota-s2-snapshot.timer`, do not create
`/etc/hotel-ota-ai/hotel-ota-cron.env`, and do not treat a scheduled S2 push as
a stability prerequisite. The previous model-driven OpenClaw S2 cron should be
disabled without replacement when the operator no longer wants scheduled S2
messages.

If scheduled reporting is reconsidered later, it must be designed as a new,
separately reviewed feature with explicit message targets, delivery monitoring,
and a dedicated deployment decision. This archive is documentation only.
