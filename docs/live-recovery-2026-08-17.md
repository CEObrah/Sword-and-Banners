# Live sync recovery, 2026-08-17

An out-of-band presentation-only rename was accidentally committed directly under `state/formations/` while the hosted campaign checkout was active. That edit was reverted exactly and made no semantic campaign change.

This runtime-neutral document exists so a stale hosted checkout whose tree still matches the pre-edit campaign state can safely fast-forward through the remote-durability neutral-path rule without adopting executable code, game/rule data, dependencies, deployment files, or campaign-state changes.

The durable fix is developed separately: presentation labels must not require casual live-state edits, and source/deployment drift must remain fail-closed without turning harmless maintenance into an unrecoverable gameplay dead stop.
