# Runtime Authority

This repository is campaign authority: mutable truth in `state/`, reusable mechanics/content in `data/`, semantic law in `rules/`, narration in `VOICE.md`. Documentation, tests/tools/caches, chat memory, and model recall never override current state.

## Startup and causal retrieval

Startup loads only `RUNTIME.md`, `VOICE.md`, `data/runtime/repository-map.json`, `state/meta.json`, `state/player.json`, and `state/scene.json`; then load the smallest causal owner/shard. Known IDs use direct refs; indexes are discovery only. Do not preload catalogs or social graphs. `REPOSITORY_MAP.md` is the read/write cookbook; `PLAYER_INTERFACE.md` is load-on-demand. Stop when enough authority is loaded. Structural writes use one exact cold file template plus the relevant system update contract.

## Player agency and intent boundary

Never invent Tang Wei's consequential voluntary dialogue, private thoughts, allegiance, surrender, spending, marriage choice, contract acceptance, mercy/execution choice, irreversible equipment choice, permanent doctrine, or strategic/political commitment. Saved delegation and standing orders may resolve only inside their stored authority.

OOC discussion, previews, hypothetical rosters/acquisitions/appointments/wars/contracts/alliances/territorial goals, and wishlists are not campaign state. Persist intent only after Tang Wei actually forms/communicates it in-world, issues an order, begins preparation, makes a commitment, or the user explicitly requests a separate noncanonical note.

## Canonical transaction contract

State change: capture persistence base/world revision; load causal owners/mechanics; resolve the whole instruction and exact reached time; settle every due/triggered/continuous process including causal wake-ups/successors; prepare one patch; validate schemas, references, conservation, information, fairness, deterministic receipts and frontier closure; re-check base; atomically persist; read back; then narrate. Reject stale-base writes; narration is not canonical before persistence.

## Time and autonomous world

A time skip closes the entire requested interval. Stable distant descendants may use declared parent army/state/faction/institution clocks when chronologically equivalent; split batching on material change and wake exact owners on direct causal effects. End with no overdue work.

Offscreen does not mean frozen. People, units, formations, armies/forces, factions, courts/institutions, mercenaries, missions/projects, training/recovery, political plans, economies, and military operations require direct or lawful aggregate process coverage. Compression changes storage/computation only and may never improve survival, training, promotion, logistics, resources, horse/equipment/instructor access, or combat results.

Autonomous owners act only from saved goals, knowledge, authority, treasury, manpower, supply, location, relationships, opposition, orders, routes, contracts, and risk. Instantiate material operations before resolving them. Persist casualties, injuries, prisoners, movement, equipment/horse/supply loss, territorial/control change, financial consequences, and successor actions.

## Unit, command, and large-battle invariants

A unit is the persistent aggregate organization/combat actor for one homogeneous troop type and one intended standard loadout/doctrine/training state. Ordinary large units remain aggregate statistical actors; never materialize one sheet per soldier. Full capability remains multidimensional. Broad mass combat may use validated compact kernels and transient vectorization, then wake full capability whenever specialists, named actors, unusual equipment/terrain, injury detail, variance/tails, or close thresholds can change the result.

Durable subset changes require a deterministic split first. Split/merge/refit rules and conservation live in `data/mechanics/unit-partition.json` and `rules/org.md`. A different target standard does not instantly issue gear; inventory, transport, shortages, fitting, ammunition, mounts, maintenance, familiarization, and elapsed time remain real. Force/replacement pools are accounting only and cannot fight until organized into units.

Command capacity is ownership-agnostic. Personal, state-issued, assigned, attached, hired, and allied-under-command units use one direct command budget. Direct personnel and direct command slots are separate simultaneous limits defined by `data/mechanics/command.json`. A subordinate command node costs one superior direct slot while its delegated units/personnel move to that subordinate's direct load. The superior retains recursive strategic authority. Commanders and staff are people, never one-person units. Command-group state lives under `state/cmd/command-groups/`; direct units/groups are peer elements; commanders remain combat-capable people.

Formations are temporary and own no manpower. Medical, logistics, signal, engineer, scout, and other support units remain real and targetable but do not automatically add line-assault frontage. Civilian camp followers remain noncombat population unless lawfully organized into a real unit.

## Information and determinism

World truth and player knowledge are separate. Information reaches Tang Wei only through valid observation, reports, scouts, couriers, officials, merchants, spies, witnesses, prisoners, or other persisted channels. Distinguish rumor, inference, and verified fact.

Structured mechanics own numerical outcomes. Model variation is not RNG. Registered randomness uses persisted seed/stream/draw rules. Same authoritative state, action, and recorded random inputs must reproduce the same mechanical result.

Cold canonical identities are routing compression, not frozen people. Materialize exact/lite state only when causal from current-date/source evidence, settled history, and registered rules. Never back-project future achievements or create free bodies, gear, offices, relationships, or capability.

## Reputation and social perception

Reputation under `state/reputation/` is sparse, audience-specific, and knowledge-gated; renown, fame, prestige, notoriety, and infamy are not universal stats. An audience changes only after direct observation or a valid report path reaches it. Relationship state and direct knowledge remain separate. Reputation never grants free knowledge/authority or directly modifies body, weapon, personal combat, or raw unit combat stats; it conditions social/morale/contract/security behavior only through the relevant domain mechanic.

Family state under `state/family/` stays separate from relationships/reputation. NPC family life requires saved motives/relationships, law/custom, opportunity, health and time. Never choose the player character's courtship, spouse, proposal response, parenthood, adoption, divorce or inheritance commitment. Birth/adoption conserves one real person/claim; kinship never auto-transfers property, office, command, allegiance or secrets.

## Narration and interface

Follow `VOICE.md`; resolve mechanics before prose. Load one primary cold scene module from `data/runtime/narration-router.json`; at most one causal secondary, never all modules. Reintroduce infrequently seen known entities with a brief player-known cue. Generate choices only at genuine unresolved decisions and follow `data/runtime/choice-presentation.json`.

`OOC:` never persists. `PREVIEW:` computes without persistence. `ORDER:` expresses in-world intent but still requires authority, mechanics, time, validation, and successful save. Questions/brainstorming are not orders.

## Maintenance boundary

One fact has one authoritative owner. Unknown JSON fields are invalid; schema/template changes are maintenance. Derived indexes/kernels are rebuildable, never truth; rebuild after authority changes. Never infer mutable appointments, army membership, ownership, inventory, territory, relationships, contracts, or player plans from documentation. Only this repository is authority; never import another game repository.

