# Repository Map

Navigation and update cookbook for the live Warring States campaign. This file is not campaign truth. Mutable facts live in `state/`; reusable mechanics/content in `data/`; semantic law in `rules/`. The machine router is `data/runtime/repository-map.json`.

## Startup

Load only `RUNTIME.md`, `VOICE.md`, `data/runtime/repository-map.json`, `state/meta.json`, `state/player.json`, and `state/scene.json`. Do not preload this document, whole armies, character rosters, markets, institutions, or catalogs.

## Retrieval discipline

1. Identify the causal question/action and affected owner IDs.
2. Known IDs use direct owner/record paths. Discovery indexes are only for unknown IDs.
3. Select one action-specific domain from `data/runtime/rule-router.json`; do not union unrelated management/economy/politics rules.
4. Follow references only if they can change legality or result.
5. Stop loading when enough authoritative context exists.
6. Derived indexes/kernels are rebuildable caches, never truth.
7. Writes modify authoritative owners first, then receipts/caches/indexes, validate, read back, then narrate.

## Minimum-context routes

| Need | First load | Deepen only when |
|---|---|---|
| Current campaign/scene | startup owners | causal action requires another owner |
| Exact/lite person | owner index prefix -> exact owner | behavior, health, relationship, career, equipment, command matters |
| Source-canon identity name | `data/people/latent-identities.json` | name/source lookup only; prove a current body before materialization |
| Home army/institution | establishment index -> one owner shard | specific unit series becomes distinct or changes |
| State/replacement pool | one `state/force-pool` owner | mobilization/allocation only; pools never fight |
| Command person | direct command-person record | direct-reporting units/nodes and capacity evaluation matter |
| Known doctrine/training | direct record path | index only for discovery |
| Known loadout | `data/loadout-records/<loadout_id>.json` | inventory/issue/custody only on use/refit |
| Market transaction | `economy_market` | treasury only if payment/close is causal |
| Treasury/revenue | `economy_treasury` | military-service economics only if force posture/recruitment is causal |
| Recruitment/service | `economy_military_service` | load logistics only if movement/supply also matters |
| Appointment/law | `politics_authority_law` | faction/war/intrigue only when causal |
| War/faction decision | `politics_factions_war` | intrigue/law only if evidence/scheme/authority matters |
| Scheme/governance | `politics_intrigue_governance` | load other politics modules only when causal |
| Unit split/refit | exact units + corresponding microdomain | never load formation/economy/training automatically |
| Formation design | template + `formation_design` | command validation/deployment are separate steps |
| Large battle | actual units + `mass_battle` | wake detailed personal/capability state only where material |
| Reputation/recognition | `state/reputation/index.json` -> subject -> one relevant audience profile | event history only for provenance/propagation/dispute |
| Family/marriage/household | `state/family/index.json#person_index` -> exact referenced record | relationship, health, House/clan/law/property, succession or reputation only when causal |
| Time skip | frontier + `time_settlement` | only due contracts/owners and causal wake-ups |

## Unit model

A **unit** is one homogeneous troop type and one intended standard loadout/doctrine/training state. It is the persistent aggregate combat actor for ordinary soldiers. Large units use multidimensional average/distribution-based capability so 5,000 soldiers do not require 5,000 character sheets. Never collapse the unit to one scalar combat rating.

A **formation** is a temporary operational/battle arrangement of units and command nodes and owns no manpower. A **force pool** is accounting/replacement manpower and cannot fight. **Commanders/staff are people**, never one-person units.

## Command hierarchy

All troops under direct control share one command budget regardless of ownership. Personal, assigned, attached, hired, allied-under-command, and institutional units do not get separate capacity ledgers.

`data/mechanics/command.json` owns two simultaneous limits: direct personnel and direct command slots. Each direct leaf unit consumes one slot plus its personnel. A subordinate commander node consumes one superior slot; its delegated units/personnel count against the subordinate instead. The superior retains recursive strategic authority over the full force.

Example: 15,000 troops in 10 direct units overload a commander comfortable at 10,000 direct personnel and 8 slots. Delegate 5,000 in 4 units to a qualified subordinate. The superior then directly carries 10,000 personnel, 6 leaf units, and 1 subordinate node = 7 slots. The subordinate carries 5,000 personnel and 4 units. Validate both nodes independently and apply real communication delay.

## Updating a unit

### Split / merge

Use `data/mechanics/unit-partition.json`. A neutral split preserves represented capability rather than rerolling better/worse children. Integer categories use deterministic allocation. Selecting veterans/specialists is a real process, not a free split option. Merge uses population-weighted moments and may reduce cohesion through integration. Transaction receipts conserve people, horses, equipment, injuries, experience, and lineage.

### Loadout boundary

Loadout is a unit property. If only 1,000 of a 5,000-infantry unit should receive a different durable loadout, split it to 4,000 + 1,000 first, then refit the 1,000-person unit. A target refit does not instantly create gear: inventory, transport, armor fitting, ammunition, horses/tack, maintenance, familiarization, money, and time remain real. Temporary shortages are issue state, not a second standard loadout.

### Doctrine / training / development

Doctrine, training, loadout, tendencies, and temporary battle orders are separate layers. Unit improvement requires elapsed time, attendance/experience, instructors, facilities, equipment, recovery, replacements, and receipts. Rebuild derived battle capability after authoritative source changes.

## Updating an NPC

1. Load exact/lite owner and the smallest relevant runtime behavior/health/relationship/knowledge/career owners.
2. Cold canon identities stay compact until causal activation. Never fabricate a current office, location, body, equipment, relationship, or future achievement merely because the name is canon.
3. A behavior-light exact/cold profile can remain restrained in a brief routine encounter. Before sustained dialogue, recurring command, or a personality-sensitive high-stakes choice, perform the behavior-depth check from role/source/canon hints, current duty, relationships, knowledge, goals, and campaign history.
4. If evidence still does not support distinctive behavior, keep the character role-driven rather than generating filler traits.
5. Skills/career advancement require real causal development and time. Office/command changes belong to institutional authorities; relationships/knowledge to their dedicated owners.

## Updating reputation and recognition

1. Load the physical/social event that actually happened before creating reputation consequences.
2. Load `reputation_event` mechanics and identify real witnesses/report origin. OOC discussion and repository omniscience are not witnesses.
3. Create one cold reputation event only if perception can materially change. Record signals, evidence quality, visibility, and report lineage.
4. Propagate through existing messenger/intelligence/institution/market/faction routes at real travel/report time. Do not create a second reputation-only global clock.
5. Update only delivered subject+audience profiles. Relationship and direct personal knowledge remain separate authorities.
6. Reputation may condition access, expectations, recruitment, contracts, morale, caution, patronage, security, or political attention only where the relevant domain rule makes perception causal. It never directly buffs combat stats or grants legal authority/knowledge.
7. Current profile is the hot truth. Historical reputation events stay cold unless explaining why an audience believes something or continuing an undelivered report.

For an NPC reaction, first determine the observer's actual audience membership/information access, then load only that audience profile. Do not load every audience that knows the subject.

`institutional_track_record_index` on legacy escort/school owners is a 0–200 factual continuity/track-record index retained from older state. It is **not** reputation, fame, prestige, notoriety, or audience knowledge. It can become evidence only when a real observer/report has access to the underlying record.

## Updating family, marriage, household, and succession

1. Start from `state/family/index.json` and the involved people. Load only referenced family records.
2. Keep institutional family status separate from relationship feelings, direct knowledge, reputation, health, property, office and command.
3. A real NPC proposal may be persisted as pending; never persist player acceptance/rejection, spouse choice, parenthood or divorce intent until the player character actually acts in-world.
4. Courtship/proposal/betrothal/marriage/adoption/guardianship/dissolution transactions use `rules/family.md` + `data/mechanics/family.json`, exact elapsed time, source refs and deterministic receipts.
5. Birth creates exactly one real child person, then parentage/household/dependent state; health resolves in its own authority. No free body or duplicate population.
6. Marriage/kinship never auto-transfer property, title, allegiance, clan/House membership, office or command. Load the exact law/House/clan/property/succession owner when those consequences are material.
7. On death, settle widowhood/dependents/guardianship before inheritance/succession. Preserve disputes and prior unions instead of deleting history.
8. Rebuild `state/family/index.json` and `state/family/kinship-index.json` after family authority changes. Kinship index is routing only.
9. Reputation/prestige effects occur only after the family event becomes known to the relevant audience through a valid information route.

## Large battle workflow

1. Load actual participating units, formation, terrain, command tree, orders, morale/cohesion/readiness, supply, support, and information picture.
2. Resolve ordinary large units as aggregate statistical actors. Use compact role/unit kernels for broad phases rather than loading every detailed capability axis at once.
3. Wake detailed capability when close thresholds, unusual equipment, terrain, specialist actions, named commanders, personal combat, detailed injuries, or variance can alter the result.
4. Command capacity affects order latency, synchronization, reserve response, and control. It never multiplies soldier body/weapon stats.
5. Medical/logistics/signals/engineers and other service units remain real targets and strategic assets but do not automatically add line-assault frontage. Civilian camp followers are noncombat population unless lawfully mobilized into units.
6. Persist casualties, wounds, prisoners/missing, horses, ammunition/equipment loss, fatigue, supply, morale/cohesion, position/control, command disruption, history, and successor operations to real unit/person owners.

## Return and reconstitution

Temporary command never transfers ownership. Returning an assigned unit restores its surviving identity to its home establishment but never resets it. Casualties, injuries, missing/prisoners, experience, promotions, morale/cohesion, equipment/horse losses, and history persist. The source owner reconstitutes from real replacement manpower, officers, stock, horses, instructors, money, facilities, and time.

## Rulebook routing

`rules/economy.md` and `rules/politics.md` are navigation indexes. Runtime mechanics live in their listed submodules. Do not load all economy/politics modules for a narrow action. Full `rules/characters.md` is for materialization/representation changes; normal interaction uses `rules/character-runtime.md`.

## What not to load by default

Do not preload all 306 cold identities, whole armies, all mercenary companies, unit catalogs, markets, political factions, relationships, doctrine/training records, items, or loadouts. Do not expand ordinary soldiers into characters. Do not use documentation/caches/indexes as state.

## Common update matrix

Use this as the default write cookbook. Resolve the exact owner ID first; then load only the named route, one structural template, and one system contract.

- Character facts/behavior/goals: `exact_characters` / `character_behavior` / `character_behavior_profile` -> `characters` contract -> exact/cold character template. Relationship, knowledge, reputation, family, health, appointment and command remain separate authorities.
- Character training/career: `npc_development` / `career_review` -> `training_development` contract and career mechanics only when causal. Never grant free development or promotion.
- Unit split/merge/refit: `unit_partition` / `unit_refit` -> `units` plus `inventory_logistics` contracts -> unit + capability/issue/refit state + transaction receipt. One troop type and one intended standard loadout per unit.
- Command/delegation: `command_tree` / `command_group` -> `command` contract -> command group/person + direct units. A subordinate command group occupies one parent slot; its commander remains an exact combat-capable person.
- Formation/deployment: `formation` / `formation_deployment` -> `formations` contract. A formation groups units for an operation/battle and never owns manpower.
- Relationship/knowledge: `relationships_knowledge` -> `relationships_knowledge` contract. Shared affiliation is not a personal relationship.
- Reputation/recognition: `reputation_subject` / `recognition_check` / `reputation_event` -> `reputation` contract. Update only audiences reached by valid evidence propagation.
- Family/kinship/succession: `family_person` / `family_kinship` / `family_transition` / `family_succession` -> `family` contract. Legal/kinship status is separate from feelings, property and reputation.
- Economy/politics/contracts: route only the specific action domain -> `economy_politics` or `contracts_processes` contract. Do not load the entire fiscal/political rulebook for a narrow transaction.
- Time/autonomous progression: `time_frontier` / process route -> `time_process` contract. Settle every due boundary through the reached time; use aggregate coverage for stable distant owners.

After any write: authority first -> transaction/event receipt where required -> derived indexes/caches -> validator stack -> read back the changed authority before narration.

## Isolation

Only this repository is authority. Never import another game repository's data, examples, IDs, mechanics, or state.

## Command-group read/write routing

- **Inspect command tree:** load the commander person/command record, `state/cmd/command-groups/index.json`, then only the referenced command-group records and direct unit/person owners needed for the requested depth.
- **Create/delegate:** validate authority and both commanders' capacities; write/update the affected command-group records; update the derived command-group index; then validate/read back.
- **Commander in combat:** load the commander person's exact/lite combat owner separately from the command group. The command group owns hierarchy only and never substitutes for the person or a troop unit.
- **Succession:** on commander incapacity, load saved deputy/successor refs and standing doctrine. If a superior absorbs the child units directly, recompute that superior's personnel and direct-slot load immediately.
- **Display:** direct troop units and subordinate command groups are peer command elements. A subordinate command group counts as one direct slot and may be shown as `<Commander> Command` with its children nested underneath.

## Structural write contract

Every gameplay-created or structurally edited JSON owner has one registered cold structural template. Templates control **shape**, not facts. System contracts control **authority and write order**, not results. Neither is gameplay state.

For any create/structural edit:

1. Identify the gameplay system and load exactly its `data/runtime/system-contracts/<system>.json` through `data/runtime/system-contract-index.json`.
2. Identify the target schema ID. Resolve only the matching first-character shard through `data/runtime/template-index.json`, then load that exact template.
3. Load the authoritative owner(s) named by the system contract. Never start from a cache/index/example.
4. Check creation prerequisites, authority, conservation, elapsed time, knowledge/agency boundaries, and causal evidence.
5. Write only registered keys/types. Unknown fields are invalid. Optional facts use registered optional fields or a registered referenced profile; never invent a new JSON key during play.
6. Dynamic/open maps may add new stable IDs only where the template explicitly permits them; each value still follows the wildcard value contract.
7. Persist authority first, receipts/history second, rebuild affected derived indexes/kernels third.
8. Run the validators required by the system contract plus `tools/test_templates.py`, then read back the changed owners before narration.
9. If the existing template cannot express a genuinely new mechanic, stop the gameplay write. Revise schema + template + system contract as maintenance first, validate, then resume.

`data/runtime/repository-map.json` is deliberately a small hot root router. Most routes live in cold `data/runtime/repository-routes/*.json` shards; use `route_index` to load **one** route shard. `data/runtime/directory-map.json` is cold maintenance/navigation metadata and is not ordinary gameplay context.

### NPC and force deepening

- **NPC:** load the exact owner first. For sustained dialogue or personality-sensitive autonomous action, use the routed behavior-depth source only when the owner lacks sufficient inline behavior. Persist new behavior only from supported evidence.
- **Unit:** load organization/identity first. A materialized unit uses its `capability_ref` when detailed unit capability matters. For broad mass-combat phases, use the routed Sword role/state combat kernel plus live unit state; do not invent per-unit `stats_ref`/`battle_kernel_ref` files that this repository does not define, and do not load every unit in the parent force.
- **Command:** load the commander/person + exact command-group nodes + only direct child units needed to the requested depth. Command groups own hierarchy, not manpower.
- **Training/development:** load only the target person/unit, its active training contract, required instructors/facilities/equipment/health, and elapsed-time process.
- **Family/reputation/social:** start from the subject/person index and load only materially relevant sparse records. Historical ledgers stay cold unless provenance matters.
- **Narration:** `VOICE.md` is the hot persona. Select one scene module through `data/runtime/narration-router.json`; a second module is allowed only if it is independently causal.
