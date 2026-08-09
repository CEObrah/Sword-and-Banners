# Runtime Authority

This repository is campaign authority: mutable truth in `state/`, reusable mechanics/content in `data/`, semantic law in `rules/`, narration in `VOICE.md`. Documentation, tests/tools/caches, chat memory, and model recall never override current state.

## Startup and causal retrieval

Startup loads only `RUNTIME.md`, `VOICE.md`, `data/runtime/repository-map.json`, `state/meta.json`, `state/player.json`, and `state/scene.json`; then load the smallest causal owner/shard. Known IDs use direct refs; indexes are discovery only. Do not preload catalogs, rosters, social graphs, armies, institutions, or narration modules. `REPOSITORY_MAP.md` is the read/write cookbook; `PLAYER_INTERFACE.md` is load-on-demand. Stop when enough authority is loaded.

Structural writes use the registered schema, exact structural template, and relevant system update contract. Existing owners, neighboring files, examples, documentation, chat context, and model inference are not structural authority. If required structure, source provenance, or causal state is missing or ambiguous, fail closed rather than improvise it.

## Player agency and intent boundary

Never invent Tang Wei's consequential voluntary dialogue, private thoughts, allegiance, surrender, spending commitment, contract acceptance, mercy/execution choice, irreversible equipment choice, permanent doctrine, marriage/family decision, appointment choice, territorial goal, or strategic/political commitment. Saved delegation and standing orders may resolve only inside their stored authority.

OOC discussion, previews, audits, hypothetical rosters/acquisitions/appointments/wars/contracts/alliances/territorial goals, comparisons, brainstorming, and wishlists are not campaign state. Persist intent only after Tang Wei actually forms/communicates it in-world, issues an order, begins preparation, makes a commitment, or the user explicitly requests a separate noncanonical note.

## Canonical transaction contract

State change: capture persistence base/world revision; load causal owners/mechanics; resolve the whole instruction and exact reached time; settle every due/triggered/continuous process including causal wake-ups/successors; prepare one patch; validate schemas, references, conservation, information boundaries, agency, fairness, deterministic receipts, and frontier closure; re-check base; atomically persist; read back; then narrate. Reject stale-base writes; narration is not canonical before persistence.

## Time and autonomous world

A time skip closes the entire requested interval. Stable distant descendants may use declared parent army/state/faction/institution clocks when chronologically equivalent; split batching on material change and wake exact owners on direct causal effects. End with no overdue work.

Offscreen does not mean frozen. People, units, formations, armies/forces, factions, courts/institutions, mercenaries, missions/projects, training/recovery, political plans, economies, family/life-course state, contracts, logistics, and military operations require direct or lawful aggregate process coverage. Compression changes storage/computation only and may never improve survival, training, promotion, logistics, resources, horse/equipment/instructor access, or combat results.

Autonomous owners act only from saved goals, knowledge, authority, treasury, manpower, supply, location, relationships, opposition, orders, routes, contracts, and risk. Instantiate material operations before resolving them. Persist casualties, injuries, prisoners, movement, equipment/horse/supply loss, territorial/control change, financial consequences, and successor actions.

## Unit, personnel, command, and large-battle invariants

A unit is the persistent aggregate organization/combat actor for one homogeneous troop type and one intended standard loadout/doctrine/training state. Ordinary large units remain aggregate statistical actors; never materialize one sheet per ordinary soldier. Full capability remains multidimensional. Broad mass combat may use validated compact kernels and transient vectorization, then wake full capability whenever specialists, named actors, unusual equipment/terrain, injury detail, variance/tails, or close thresholds can change the result.

Ordinary recruitment is a conserved aggregate transfer from an exact source owner stratum or manpower pool into an accounting pool or homogeneous unit. Recruitment itself never creates one person record per recruit. The destination inherits or conservatively recomputes source capability, age, body, aptitude, experience, qualification, and other development inputs when causally relevant. Missing source ownership, source depletion evidence, or necessary capability detail fails closed. A named standout, commander, specialist, prisoner, casualty, award recipient, or recurring NPC materializes only through a separate evidence-backed transaction that identifies one real surviving body exactly once and preserves already-settled history.

Durable subset changes require a deterministic split first. Split/merge/refit rules and conservation live in `data/mechanics/unit-partition.json` and `rules/org.md`. A different target standard does not instantly issue gear; inventory, transport, shortages, fitting, ammunition, mounts, maintenance, familiarization, and elapsed time remain real. Force/replacement pools are accounting only and cannot fight until organized into units.

Command capacity is ownership-agnostic. Personal, state-issued, assigned, attached, hired, and allied-under-command units use one direct command budget. Direct personnel and direct command slots are separate simultaneous limits defined by `data/mechanics/command.json`. A subordinate command node costs one superior direct slot while its delegated units/personnel move to that subordinate's direct load. The superior retains recursive strategic authority. Commanders and notable/materialized staff are people, never one-person units. Routine headquarters staff functions may remain anonymous command-staff role slots until individual agency becomes causal. Command-group state lives under `state/cmd/command-groups/`; direct units/groups are peer elements; commanders remain combat-capable people.

Formations are temporary and own no manpower. Scouts, engineers, sappers, logistics, signals, and other explicitly military specialists may be units according to their registered troop type and support class. Scouts are reconnaissance troops, not couriers. Medical personnel, stretcher crews, healers, physicians, couriers, administrative runners, dependents, and ordinary camp followers are civilian/camp-support populations, never military units and never military unit command slots. If a civilian support person is lawfully mobilized into combat service, transfer that real person into a registered non-medical, non-courier troop type and stop counting that person in the civilian support source for the same interval. Armed train guards are separate homogeneous guard units.

## Information and determinism

World truth and player knowledge are separate. Information reaches Tang Wei only through valid observation, reports, scouts, couriers, officials, merchants, spies, witnesses, prisoners, staff, or other persisted channels. Distinguish rumor, estimate, inference, and verified fact.

Structured mechanics own numerical outcomes. Model variation is not RNG. Registered randomness uses persisted seed/stream/draw rules. Same authoritative state, action, and recorded random inputs must reproduce the same mechanical result.

Static identity-catalog entries are source names only and create no current body or personal clock. Current people develop through exact/lite owners, aggregate populations, units, institutions, or anonymous role slots. Materialize a named person only after current existence and one conserved source person/slot are proven; never back-project future achievements or create free bodies, gear, offices, relationships, information, or capability.

## Reputation, social perception, and family

Reputation under `state/reputation/` is sparse, audience-specific, and knowledge-gated; renown, fame, prestige, notoriety, and infamy are not universal stats. An audience changes only after direct observation or a valid report path reaches it. Relationship state and direct knowledge remain separate. Reputation never grants free knowledge/authority or directly modifies body, weapon, personal combat, or raw unit combat stats; it conditions social/morale/contract/security behavior only through the relevant domain mechanic.

Family state under `state/family/` stays separate from relationships/reputation. NPC family life requires saved motives/relationships, law/custom, opportunity, health, and time. Never choose the player character's courtship, spouse, proposal response, parenthood, adoption, divorce, inheritance commitment, or other consequential family decision. Birth/adoption conserves one real person/claim; kinship never auto-transfers property, office, command, allegiance, or secrets.

## Narration and interface

Follow `VOICE.md`; resolve mechanics before prose. Load one primary routed scene module from `data/runtime/narration-router.json`; at most one causal secondary, never all modules. Reintroduce infrequently seen known entities with a brief player-known cue. Generate choices at every genuine unresolved decision according to `data/runtime/choice-presentation.json` unless the player has already declared the next action for that resulting state.

During play, diagnose real repository/runtime/narration defects when they become apparent. A behavior-preserving, structurally safe repair covered by the player's standing maintenance authorization may be applied through the normal isolated-branch, validation, stale-base and readback workflow without separate confirmation; mention a concise `OOC:` note only when useful. Standing maintenance authority never permits changing campaign facts, player agency, balance, irreversible content design, or a materially ambiguous design choice. Those remain proposals until explicitly authorized. Maintenance does not advance world time or turn OOC discussion into campaign state.

`OOC:` never persists. Ordinary in-world natural-language declarations are gameplay instructions and still require authority, mechanics, time, validation, and successful save. Questions, hypotheticals, comparisons, audits, and brainstorming are nonpersistent unless the player actually forms or communicates the intent in-world.

## Maintenance boundary

One fact has one authoritative owner. Unknown JSON fields are invalid; schema/template changes are maintenance. Derived indexes/kernels are rebuildable, never truth; rebuild after authority changes. Never infer mutable appointments, army membership, ownership, inventory, territory, relationships, contracts, or player plans from documentation. Only this repository is authority; never import another game repository.

Creating a mutable owner is deterministic template instantiation, never free-form JSON authorship. Resolve the exact target schema through `data/runtime/template-index.json`, load its registered structural template, and render its registered blank creation skeleton before filling facts. The blank skeleton is derived only from the target structural contract and contains no guessed gameplay values. Structure must never be copied from a neighboring owner, example record, prose description, chat/model memory, or semantic similarity. Optional allowed fields are not permission to invent them. If a required gameplay fact cannot be lawfully resolved, or if a needed field is absent from the target template, abort the gameplay write and perform schema/template/system maintenance first. CI must prove that every mutable target schema can render a deterministic blank creation skeleton.

Live gameplay rules and canonical gameplay owners contain only current behavior and current state. Semantic gameplay IDs, paths, record IDs, unit IDs, doctrine IDs, and training IDs do not encode release versions. Schema/validator compatibility identifiers and stable deterministic seed strings are technical metadata rather than campaign identity and change only when their own contracts or deterministic inputs change.

Ordinary maintenance that preserves a formal structural contract updates current semantic IDs and files in place. Do not mint versioned gameplay IDs, clone rules, or bump campaign/system versions merely to mark an edit. Schema or validator compatibility versions change only when the formal structural contract actually requires a compatibility boundary. Validation remains mandatory after repository maintenance whether or not any version identifier changes.

Repository maintenance must not expose half-fixed `main` revisions as the normal workflow. Assemble related maintenance changes on a temporary branch, run the complete validator stack there, and fast-forward `main` only after that candidate is green and the main persistence base is rechecked. Gameplay transactions may use the same candidate-validation pattern when practical. A failed validation branch is evidence for repair, not campaign canon.
