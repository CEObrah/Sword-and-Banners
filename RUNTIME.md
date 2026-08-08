# Runtime Authority

This repository is campaign authority: mutable truth in `state/`, reusable mechanics/content in `data/`, semantic law in `rules/`, narration in `VOICE.md`. Tests, caches, documentation, chat memory, and model recall never override canonical state.

## Startup and routing

At startup read only `RUNTIME.md`, `VOICE.md`, `data/runtime/repository-map.json`, `state/meta.json`, `state/player.json`, and `state/scene.json`. Then load the smallest causal neighborhood. Known IDs use direct refs; indexes are discovery only. Do not preload catalogs, rosters, social graphs, armies, institutions, or narration modules. `REPOSITORY_MAP.md` is the load-on-demand read/write cookbook; `PLAYER_INTERFACE.md` is load-on-demand.

Structural writes use the registered schema, structural template, and relevant system update contract. If required structure or causal state is missing, fail closed rather than infer it from neighboring files, examples, prose, or chat context.

## Agency and state changes

Never invent Tang Wei's consequential voluntary dialogue, private thoughts, allegiance, surrender, spending commitment, contract acceptance, mercy/execution choice, irreversible equipment choice, permanent doctrine, marriage/family decision, appointment choice, territorial goal, or strategic/political commitment. Saved delegation and standing orders resolve only inside stored authority.

`OOC:` discussion, audits, previews, comparisons, hypotheticals, and wishlists never persist. In-world declarations are gameplay instructions and still require lawful authority, mechanics, elapsed time, validation, and successful persistence.

For every state change: capture the main persistence base and world revision; load causal owners/mechanics; resolve the full instruction and exact reached time; settle every due, triggered, continuous, awakened, or successor process; prepare one patch; validate schema, references, conservation, information, agency, fairness, determinism, and frontier closure; re-check the base; atomically persist; read back; only then narrate. Reject stale-base writes.

## Time and world fairness

A time skip closes the entire requested interval. Offscreen does not mean frozen: people, units, armies, factions, institutions, mercenaries, projects, training/recovery, politics, economy, logistics, military operations, family/life-course, contracts, and successor plans remain subject to registered clocks or lawful aggregate processes.

Compression may reduce storage or computation only. It may never improve survival, training, promotion, logistics, resources, equipment, horses, instructor access, or combat outcomes. Split batching on material change; wake exact owners on direct causal effects. End with no overdue work.

Autonomous owners act only from saved goals, knowledge, authority, resources, location, relationships, opposition, orders, routes, contracts, and risk. Material operations must exist before consequences settle. Persist casualties, injuries, prisoners, movement, losses, territorial/control changes, financial effects, and successor actions.

## Units, personnel, and command

A unit is one persistent aggregate organization/combat actor for one homogeneous troop type and one intended standard loadout, doctrine, and training state. Ordinary troops remain aggregate; never create one person owner per soldier. Full unit capability stays multidimensional. Battle kernels and vectorization are derived acceleration only; wake full capability when variance, specialists, named actors, unusual terrain/equipment, injuries, or close thresholds can change the result.

Durable subset differences require deterministic split/merge/refit transactions under `data/mechanics/unit-partition.json` and `rules/org.md`. People, equipment, mounts, ammunition, injuries, experience, and history remain conserved. A target loadout never creates instant issue. Force/replacement pools are accounting only and cannot fight until organized into lawful units.

Recruitment is a conserved aggregate transfer from a real source owner stratum or manpower pool. The destination inherits source capability and demographic inputs when relevant. Recruitment does not create ordinary person owners. A standout, specialist, commander, prisoner, casualty, award recipient, or recurring NPC materializes only through a separate transaction identifying one real body exactly once.

Command capacity is ownership-agnostic. Personal, state-issued, attached, hired, and allied-under-command forces share direct-personnel and direct-command-slot limits in `data/mechanics/command.json`. Delegation moves direct load to subordinate command groups while preserving superior strategic authority. Commanders and staff are people, never one-person troop units. Formations own no manpower.

Military specialists may be units only under registered troop/support classes. Civilian medical personnel, couriers, dependents, and ordinary camp followers are not military units or command slots. Transfer into combat service must remove the same people from their civilian source for the same interval.

## Information and determinism

World truth and Tang Wei's knowledge are separate. Information reaches him only through valid observation, reports, scouts, couriers, officials, merchants, spies, prisoners, witnesses, staff, or other persisted channels. Keep rumor, inference, estimate, and verified fact distinct.

Structured mechanics own numerical outcomes. Model variation is not RNG. Registered randomness uses persisted seed/stream/draw rules; the same authoritative state, action, and recorded random inputs must reproduce the same result.

Materialize exact/lite people only from current causal evidence, settled history, and registered rules. Never back-project future achievements or create free bodies, gear, offices, relationships, information, or capability.

## Social and family boundaries

Reputation is sparse, audience-specific, and knowledge-gated. Relationships, direct knowledge, reputation, family, property/economy, appointments/command, contracts, and political standing are separate authorities; none automatically grants another.

NPC family/life state resolves from saved motives, relationships, law/custom, opportunity, health, and time. Never choose Tang Wei's courtship, spouse, proposal response, parenthood, adoption, divorce, inheritance commitment, or other family decision. Kinship never automatically transfers property, office, command, allegiance, or secrets.

## Narration and interface

Resolve mechanics before prose and follow `VOICE.md`. Load one primary narration module through `data/runtime/narration-router.json`, with at most one independently causal secondary. Repository memory is not player memory.

At a genuine unresolved player decision, use `data/runtime/choice-presentation.json` unless the player already supplied the next action. Reintroduce infrequently seen known entities with a short player-known cue. Surface a concise `OOC:` note only when an actual runtime/repository/narration defect matters.

## Maintenance boundary

One fact has one authoritative owner. Unknown JSON fields are invalid. Derived indexes, summaries, and kernels are rebuildable caches, never competing truth. Never infer mutable appointments, ownership, inventory, territory, relationships, contracts, or plans from documentation.

Creating or structurally changing a mutable owner requires its registered schema/template/system contract and deterministic blank creation skeleton. Optional fields are not permission to invent facts. Schema, field shape/type/nesting/cardinality changes are maintenance and must update registered authorities and validators before gameplay uses them.

Active gameplay rules and owners state current behavior only; migration history and deprecated behavior belong in maintenance infrastructure. Stable gameplay IDs do not encode release history.

Repository maintenance is assembled on a temporary branch, fully validated, stale-base checked against `main`, then fast-forwarded and read back. Never expose a half-fixed `main`, and never claim a save/commit/push that did not succeed.
