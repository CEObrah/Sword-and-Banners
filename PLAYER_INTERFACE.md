# Sword & Banners Player Interface

## Normal gameplay

Interpret the player's natural-language intent and call the Sword runtime through semantic commands. Narrate only committed results. Do not perform gameplay arithmetic in chat and do not edit campaign JSON manually.

The player-facing runtime actor is Tang Wei. Player tools may use `gameplay` mode only. Internal autonomous and maintenance actors are not exposed to the player surface.

Mutable truth is loaded through authoritative owner references. Combat takes saved `formation_ref` values and the runtime derives personnel, ownership, command authority, location, readiness, morale, cohesion, doctrine, training, equipment, logistics, fatigue and commander state itself.

## OOC

OOC inspection is read-only. Explain current mechanics or player-visible campaign state without advancing time. Hidden state remains hidden unless the user explicitly requests a developer-level audit and the interface is operating in OOC DEV.

## OOC DEV

OOC DEV may inspect code and campaign state, run tests, and change runtime code. A confirmed campaign-state error must be corrected through the explicit trusted `repair` maintenance transaction. Maintenance never counts as gameplay time.

## Authority rules

`runtime/` contains execution machinery. `game/` contains Sword rules and static setting data. `state/` contains current campaign truth. Git commits are the canonical campaign history. Retired execution systems in `archive/legacy-execution/` are reference material only and must never be loaded as mutable authority.

Ownership and operational command are distinct. Personal troops, House troops, state troops and temporary attachments retain their administrative owner when command authority changes.

House Champions are a protection/extraction formation. Their primary success condition is: **Tang Wei returns alive.**
