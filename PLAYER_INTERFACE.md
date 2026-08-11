# Sword & Banners Player Interface

This root file is a compatibility summary. The active ChatGPT operating guide is `plugins/sword-and-banners/skills/sword-and-banners-game-master/`.

## Normal gameplay

Interpret the player's natural-language intent and call the Sword runtime through semantic commands. Narrate only committed results. Do not perform authoritative gameplay arithmetic in chat and do not edit campaign JSON manually.

The player-facing runtime actor is Tang Wei. Player tools may use `gameplay` mode only. Internal autonomous and maintenance actors are not exposed to the player surface.

Every live turn begins from fresh bounded play context. The current runtime command catalog is dynamic authority for what persistent actions are supported. The player never needs to write command names, payload JSON, revisions, request IDs, or repository paths.

A persistent write follows:

`natural-language intent -> fresh context -> one semantic command -> preview -> exact attested execute -> fresh context -> narration`

Deterministic commands may expose projected preview results. Contested battle, personal-combat, and siege-assault previews intentionally expose readiness without revealing the outcome, preventing repeated preview from becoming a stochastic oracle.

Mutable truth is loaded through authoritative owner references. Combat derives personnel, ownership, command authority, location, readiness, morale, cohesion, doctrine, training, equipment, logistics, fatigue, and commander state from saved campaign data rather than caller-supplied outcome fields.

## Bounded reads

The ChatGPT MCP service exposes player-safe tools for current play context, exact permitted person reads, exact permitted object reads, and read-only OOC audit. Hidden IDs may not be guessed to browse campaign truth.

## OOC

`OOC:` inspection is read-only. Explain current mechanics or player-visible campaign state without advancing time. World truth remains distinct from player knowledge.

## OOC DEV

`OOC DEV:` may inspect code and campaign state, run tests, and change source when requested. A confirmed campaign-state error must be corrected through an explicit trusted repair or migration with provenance. Maintenance never counts as gameplay time.

## Authority rules

`runtime/` contains execution machinery. `game/` contains Sword rules and static setting data. `state/` contains current campaign truth. Git-backed committed state is durable campaign history. Retired execution systems in `archive/legacy-execution/` are reference material only and must never be loaded as mutable authority.

Ownership and operational command are distinct. Personal troops, House troops, state troops, and temporary attachments retain their administrative owner when command authority changes.

House Champions are a protection/extraction formation. Their primary success condition is: **Tang Wei returns alive.**

Choice menus are nonbinding examples. The player may always type another natural-language action.
