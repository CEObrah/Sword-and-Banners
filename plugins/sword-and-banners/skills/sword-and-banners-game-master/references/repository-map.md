# Repository Map

Use this reference for `OOC DEV:` source routing. `runtime/contracts/repository-map.json` is the machine router; this file records the important ownership boundaries only.

## Top-level authority

`runtime/` — executable engine, planners, API/MCP, causal simulation, transactions, persistence, recovery.

`game/` — static rules, schemas, mechanics, world/reference data, institutions, equipment, economy, doctrine.

`state/` — current mutable campaign truth. Records explicitly marked `authority: false` are indexes/projections/routing only.

`plugins/sword-and-banners/skills/sword-and-banners-game-master/` — canonical GM Skill source; not mechanical authority.

`tests/runtime/` — current runtime/invariant/integration verification.

`tools/` — current structural validation, focused test routing, release verification, and maintenance utilities.

## Core runtime owners

`runtime/sword_runtime/engine.py` — baseline domain reducers and mechanics.

`runtime/sword_runtime/service_runtime.py` — production runtime composition, player-agency hardening, durability wiring, non-probing preview behavior.

`runtime/sword_runtime/production_planner.py` — final production planner composition.

`runtime/sword_runtime/cohort_personnel.py` — conserved aggregate recruitment/development cohorts, deterministic background/selection distributions, formation lifecycle slices, combat experience, and materialization synchronization.

`runtime/sword_runtime/recruitment_campaigns.py` — high-resolution aggregate candidate campaigns for Wei: real population reservation, registered selection, training/cost/capacity settlement, final cohort intake, and cancellation return.

`runtime/sword_runtime/combat_capability.py` — representation-neutral troop capability kernel for cohort skills/attributes, weapon reach/minimum range, missile range/cadence/ammunition, protection, mounts, frontage, and separate named/person-lite/commander/deputy contribution.

`runtime/sword_runtime/personal_combat.py` + `runtime/sword_runtime/contact_physics.py` + `runtime/sword_runtime/anatomy.py` — exact-person continuous combat authority: N-actor local geometry/timing, cumulative whole-body active-defense load with distinct-attacker reaction saturation, separate weapon/shield readiness and orientation, projectile release/contact, layered shield/armor contact, structural anatomy, bleeding/shock/respiratory physiology, persistent injury function, and exact personal ammunition state. Static tuning is in `game/data/mechanics/combat.json` and `game/data/mechanics/injury.json`.

`runtime/sword_runtime/combat_capability.py#_combat_hero_interventions` + `runtime/sword_runtime/engine.py#battle_resolve` + `runtime/sword_runtime/battle_trace.py` — bounded named-person battlefield intervention bridge. It keeps anonymous troops aggregate while resolving representative local contacts through real equipment layers, exact named ammunition/risk, officer/cohesion/artillery pressure, command-attention cost, and player-visible causal trace.

`runtime/sword_runtime/fortified_site_runtime.py#_siege_bed_crossbow_physics/_siege_prepare_fortress_artillery` — fixed bed-crossbow mechanism/crew/range/ammunition/contact authority for fortified-site fire. Mechanism condition owns launch energy; crew capability owns pointing, timing, dispersion, and cycle execution.

`runtime/sword_runtime/officer_cadre.py` — aggregate embedded officer-cadre casualty/reorganization owner. Named hero officer-targeting pressure may reclassify already-conserved battle casualties toward officer bodies but never creates extra deaths.

`runtime/sword_runtime/house_tang_development.py` — House Tang/Sword Manor aggregate development, lawful intake, and aggregate rank progression.

`runtime/sword_runtime/smart_training.py` — compatibility/intention routing for deterministic training; gain-bearing mechanics live in the closed registered-program owners below.

`game/data/mil/deterministic-training-programs.json` + `runtime/sword_runtime/training_programs.py` — canonical closed drill/program rotations, role/billet resolution, adaptive weighting only inside registered programs, physical drill access, exact/person-lite/cohort settlement, and deterministic combat EDU weighting. ChatGPT never authors gain-bearing exercises or stat focuses.

`runtime/sword_runtime/training_instructors.py` — best lawful present instructor selection, domain-relative teaching quality, distributed formation drill capacity, instructor-duty reservation, and exact-person equipment/facility access.

`runtime/sword_runtime/training_time.py` — one exact/person-lite waking-time ledger shared by deliberate training and teaching duty; overlapping work cannot mint extra hours.

`runtime/sword_runtime/training_facilities.py` — physical `facility_tag` resolution against saved location/containment plus specialist shared training resources; generic field setups cannot invent artillery/engineering infrastructure.

`runtime/sword_runtime/training_promotion.py` — promotion-aware training priority from real saved progression gates only.

`runtime/sword_runtime/fatigue.py` + `game/data/mechanics/fatigue.json` — common work/rest fatigue clock used by training, travel, combat and other physical activity owners.

`runtime/sword_runtime/unit_establishment.py` — authorized Unit establishment and hierarchy: minimum 500, multiples of 500, casualty-independent establishment, commander/deputy outside fighting strength, internal 100/500/1,000 command bodies conserved inside fighting strength.

`game/data/mechanics/house-tang-force-policy.json` — static House Tang recruitment/training/force-employment policy. Sword Manor, the Four Bastion Corps, and House elite progression use distinct conserved entry/progression pipelines; mercenary preference never changes manpower ownership.

`runtime/sword_runtime/house_tang_economy.py` — transfer-based House commercial services, bounded Sword Manor escort/security work, and zero-body contingency mercenary offer routing. `state/contract/sword-manor-service-jobs.json` owns obligations/results only, never Sword Manor bodies.


`runtime/sword_runtime/cohort_tx_support.py` — formation training isolation and exact/person-lite materialization from already conserved cohort slots.

`runtime/sword_runtime/development.py` — exact/person-lite development and combat-experience settlement.

`runtime/sword_runtime/progression_integrity.py` — named-person progression proof/provenance owner. It distinguishes verified deliberate time from gain-bearing module time, proves completed-cycle shortfalls, and records cohort-inherited capability baselines without double-awarding historical EDU. Current exact command route/life-host reconciliation remains in `service_runtime.py` + `activity_living_world.py`.

`tools/repair_progression_integrity.py` — explicit OOC maintenance repair for deterministic-training migrations. It may settle only numerically proven completed-cycle shortfalls and records provenance; zero-cycle representation baselines and cohort-inherited development are never retroactively re-awarded.

`runtime/sword_runtime/living_world.py`, `causal_living_world.py`, `production_living_world.py` — bounded causal scheduling, wakes, and production settlement.

`runtime/sword_runtime/systems/campaign_events.py`, `campaign_event_planner.py`, `institutional_processes.py`, `world_arcs.py` — event/front/institutional causal work and report routing.

`runtime/sword_runtime/vitality.py` — read-only playability/causal-throughput diagnostics.

`runtime/sword_runtime/civil_world.py` — production causal bridge for private production, exact capital markets/scarcity pricing, funded/cancellable institution projects, sourced granary procurement, differentiated knowledge-gated faction actions, evidence-gated world-arc actor/domain dispatch, dynamic interstate front discovery, weighted local-site projections, conserved occupation revolts, House-polity progression, recognized-polity institutions/monthly autonomy/shared interstate fronts, autonomous irregular revolt routing, and occupation/governance integration. It does not replace exact state, market, institution, faction, polity, territory, treasury, population, force, or private-economy owners.

`game/data/mechanics/civil-economy.json` — canonical aggregate civil production, project-input, market-normal-stock, House estate, granary procurement, and occupation integration parameters.

`state/economy/merchant-houses.json` — exact mutable registry for named merchant-house capital, credit policy, conserved loans, repayments, and provenance. It is capital/credit authority, not a substitute for physical market stock or private-economy commodity ownership.

`state/contract/tang-supply-contracts.json` — House Tang material supply-contract terms. Production settlement realizes deliveries through exact source depots/private economy and records shortfall rather than materializing missing food or fodder.

`runtime/sword_runtime/bastion_personnel.py` + `game/data/mechanics/bastion-corps.json` — permanent Four Bastion Corps applicant reservation, Corps qualification, active-vacancy admission and conserved replacement/reconstitution. Bastion bodies are House Tang military personnel, never mercenary-market bodies.

`state/merc/market.json` — `authority:false` projection of the represented mercenary labor market and short-notice availability. Exact named/regional companies and `state/merc/local.json` remain the conserved manpower owners; contracts never transfer their bodies.

`game/data/politics/faction-profiles.json` — canonical differentiated starting goals/resources/action vocabularies for autonomous faction owners.


`runtime/sword_runtime/player_group_actions.py` — causally parallel grouped player military actions.

`runtime/sword_runtime/army_organization.py` — recursive zero-body army organization review and NPC staffing. Direct Units may be persistent formations or intact Nested Armies; descendants are never flattened or duplicated, and Tang Wei is never autonomously restaffed behind player agency.

`runtime/sword_runtime/fortified_site_logistics.py` + `runtime/sword_runtime/fortified_site_runtime.py` — universal fortified-site hot/cold logistics. Static fort/city/pass blueprints stay cold until strategically relevant; hot sites materialize finite military depots, installed fixed equipment, magazines, garrison stores, repair/medical/water/wagon state, and conserved replenishment.

`runtime/sword_runtime/independent_organizations.py` — generic zero-population non-sovereign organization lifecycle: exact treasury, existing-person membership/leadership, linked normal force owners, shared physical projects, maintenance and dissolution.

`runtime/sword_runtime/merchant_convoys.py` — selectively materialized strategic merchant cargo. Routine trade remains aggregate; exact convoys conserve source stock, merchant capital, route transit, destination payment and unsold cargo. Material convoys can reroute around damaged routes, carry exact mobilized escort formations with their own supply/casualty state, and be physically interdicted/seized/destroyed by an exact formation inside the route-node time window.


`runtime/sword_runtime/strategic_crossings.py` — four strategic river-crossing blueprints plus mutable water stage, bridge condition, ferry serviceability and ford state; route planning and army throughput use the physical bottleneck.

`state/geography/strategic-crossings.json` — compact authoritative mutable crossing condition owner. Static dimensions remain in `game/data/world/routes.json`.

`runtime/sword_runtime/army_train_logistics.py` — one exact aggregate baggage-train/camp owner per materially moving recursive army or standalone strategic formation. It transfers conserved depot cart teams, references formation-owned cargo, allocates driver/guard duties from existing personnel, persists cart damage/loss/delay, camp sectors and relief corridors, and creates zero personnel.

`state/logistics/army-trains/index.json` — authority:false routing index for exact materialized army trains.
`game/data/mechanics/military-career.json` — durable military rank ladder and rank/billet/span separation. Only explicit promotion/demotion changes rank; relief, reserve, retirement, casualties and reassignment do not.

`state/organizations/index.json` — `authority:false` routing for exact generic organization owners.

`state/economy/merchant-convoys.json` — `authority:false` routing for exact materialized merchant-convoy cargo owners under `state/economy/convoys/`.

## Recruitment and combat data authorities

`game/data/mil/recruitment-cohort-profiles.json` — canonical background distributions, registered selection profiles, role training focuses, and candidate source mixes. ChatGPT never invents recruitment stats.

`game/data/mil/combat-role-profiles.json` — canonical role skill/attribute weights, loadout selection, and formation spacing/depth role parameters.

`game/data/mechanics/formation.json` — canonical mass-battle frontage, reach/range/contact and weapon-interaction rules.

`runtime/sword_runtime/battlefield.py` + `game/data/mechanics/battlefield-operations.json` — persistent operational battlefield sectors, assignments, timed redeployment, local pressure, delegated reserve initiative, and delayed reports. This layer never owns casualties or territory; exact battle/personal combat remains consequence authority.


`game/data/loadout-records/*.json` and item/equipment registries — canonical weapon reach, minimum range, missile range/cadence, armor/shield properties, mounts, ammunition type, and carried load.

`state/recruitment/candidate-pools.json` — current aggregate reserved candidate campaigns; rejected candidates return to their conserved source strata.

## Player-facing API

`runtime/sword_runtime/api/operations.py` — core read/command operations and OOC audit composition.

`runtime/sword_runtime/api/stable_operations.py` — bounded player-safe context, exact continuation reads, safe interaction surface, wake-aware availability.

`runtime/sword_runtime/api/household_operations.py` — bounded direct-family scene projection. It follows existing family routing but marks a relative present only when that person's exact current location matches Wei; it also exposes present relatives as lawful direct interaction targets without turning household residence into presence.

`runtime/sword_runtime/api/interaction_surface.py` — player-owned `interaction_action` admission/translation and safe interaction/report handles.

`runtime/sword_runtime/api/mcp.py` / `runtime/sword_runtime/api/mcp_extensions.py` — OAuth MCP surface, preview attestation, bounded continuation tools.

`runtime/sword_runtime/api/app.py` — service app and one production runtime instance.

`runtime/sword_runtime/api/world_reference.py` — bounded cold reference search; never current-state authority.

## Transactions

`runtime/sword_runtime/tx/coordinator.py` — transaction lifecycle, commit, durability, receipt publication, recovery.

`runtime/sword_runtime/tx/wal.py` — current partitioned WAL only.

`runtime/sword_runtime/tx/receipts.py` — immutable idempotency receipts.

`runtime/sword_runtime/tx/remote.py` / `git.py` — remote and local Git durability.

`runtime/contracts/transaction-invalidations.json` — exact tombstones only for deliberate repairs that remove previously receipted transactions.

## Current campaign anchors

`state/meta.json` — campaign/player IDs, current revision, world time, seed.

`state/player.json` — Tang Wei exact player record.

`state/scene.json` — authored presentation shell/projection, never a replacement for exact current owners when stale.

`state/runtime.json` — causal frontier, hosts/events, wake state.

`state/index/owner-index.json` — exact owner routing.

`state/index/location-formation-index.json` — non-authoritative formation location routing.

`state/index/commander-formation-index.json` — non-authoritative commander routing.

`state/relationships.json` — current relationship authority.

`state/information/index.json` — information routing; exact claim `knowers` govern knowledge.

`state/information/institutional-awareness.json` — exact audience-scoped identity awareness for major public/institutional subjects. It grants recognition only inside listed court/military/nobility/merchant networks and never substitutes for personal relationships, secret knowledge, or confidential force data.

`state/history/events/index.json` — bounded authoritative semantic-history head and archive routing. `runtime/sword_runtime/history_store.py` spills older exact events into `state/history/events/archive/*.json`; archive segments remain exact history and are rehydrated only when needed.

`state/politics/treaties.json` — first-class exact interstate treaty/ceasefire authority. Military control never silently resolves legal claim; settlement terms, truce horizon, parties, territorial status, and provenance live here and are linked from state diplomacy.

`state/factions/*.json` — mutable exact faction agendas/resources/relationships/knowledge windows. Independent powers such as the northern steppe confederation require their own exact faction owner rather than being routed through another polity.

`runtime/sword_runtime/causal_event_store.py` — bounded causal-event hot head, exact archive segments, deterministic hash-route shards, and archive-aware discovery for player-facing reports. Archive metadata is a bounded window and never the authority for archived event existence.

`tools/repair_causal_host_horizons.py` — explicit OOC-only repair for stale recurring-host `safe_through` metadata when an already-scheduled future `next_due` event proves the correct horizon. It never advances time, runs a host, or changes campaign-domain truth.

`state/politics/polities/*.json` — exact mutable sovereign-polity owners created only by lawful House-backed territorial authority. Personal battlefield command is never sovereign entitlement. Active polities receive their own monthly causal host; recognized/proto polities can participate in shared interstate fronts, treaty diplomacy, territorial taxation/recruiting, world-arc dispatch, and exact threat-response operations while local populations/economies remain in their physical owners. House identity, territorial control, recognition, treasury, military force, and occupation administration remain separate linked authorities.

`state/territory/control.json#sites.*.local_baseline` — authority:false persistent weighted demographic/tax allocation projection for local-site fidelity. Exact people remain conserved only in the native population owner.

`state/formations/*.json` — persistent exact formation records whose members may be aggregate cohorts.

`state/forces/*.json` / `state/population/*.json` — conserved manpower/population authorities.

## Release verification

`tools/validate_release.py` — current-only structural/schema/conservation validation.

`tools/quick_check.py` — fast release gate.

`tools/test_changed.py` — focused changed-path regression router.

`tools/run_release_suite.py` — deliberate full current release verification.

Keep one writable authority path per domain and avoid duplicate root manuals or execution trees.

## Human-scale campaign depth routes

- `runtime/sword_runtime/api/command_discovery.py`: compact semantic-command discovery; fetch one exact command contract afterward.
- `runtime/sword_runtime/campaign_depth.py`: retinue/command-group training, information, investigations, commissions, commitments, and medical treatment.
- `state/cmd/command-groups/`: persistent command-only hierarchy; owns zero manpower.
- `state/investigations/`: exact investigation owners plus actor-routing index.
- `state/commissions/`: durable request/offer owners plus actor-routing index.
- `state/commitments/`: durable obligation owners plus actor-routing index.
- `state/information/subject-index.json`: discovery-only subject routing for exact information claims.

Use the exact ref returned by player-safe context or an index. Do not scan these directories to infer hidden state.
## Routed world geography

- `game/data/world/locations.json` owns static location identity, taxonomy, containment, state/region parentage, strategic-node eligibility, demographic eligibility, and fortified-parent containment. A location record is not by itself mutable control, population, garrison, or stock authority.
- `game/data/world/location-functions.json` defines what each location function tag actually means: direct mechanical gate, deterministic simulation weight, information-delivery channel, strategic classification, reference-only tag, or scene anchor. A tag never gains stronger authority than its registered role.
- `game/data/world/routes.json#routes` owns strategic route identity/endpoints/base travel inputs. `#local_routes` owns compound/settlement/internal access. 
- `game/data/mechanics/travel-geography.json` owns deterministic movement-mode, terrain, and road-quality factors. `runtime/sword_runtime/geography.py` owns bounded route/containment/path queries used by travel, formation movement, convoys, and fortification containment.
- `state/territory/control.json#route_states` owns only persistent current route usability/disruption/control linkage. It never replaces static route identity. `state/index/geography-index.json` is `authority:false` routing/cache data.
- `state/population/*.json#local_population` partitions exact national population only across legitimate demographic owners. Facilities, gates, depots, offices, training grounds, and halls do not become national demographic regions. `state/economy/private/*.json#local_regions` follows that partition without becoming population authority.
- `state/forces/*.json#available_by_location` and cohort `reserve_by_location` are nested spatial partitions of their exact force owners. `state/mounts/*.json#regional_reserve` is the corresponding conserved mount reserve partition. Neither creates a second owner.
- `game/data/world/fortification-profiles.json` owns lazy static physical blueprints and explicit route-control relationships. Exact persistent fortification condition exists only after materialization under `state/fortifications/`; `state/fortifications/index.json#static_profiles` is discovery-only. Child facilities inherit enclosing-perimeter facts through location containment and do not duplicate wall state.
- `game/data/world/minor-polities.json` is cold/reference classification only. Readiness/capability never creates exact population or troops; living minor-polity population/forces must use normal exact state owners.


`runtime/sword_runtime/political_depth.py` — evidence-aware sovereign court procedure and bounded multilateral coalition conferences. Exact information/investigation owners remain evidence authority; court assessment and judgment stay separate. Conference invitations travel through ordinary diplomatic proposals and never force membership.

`state/politics/diplomatic-conferences/index.json` — authority:false routing for exact multilateral conference owners.

`runtime/sword_runtime/settlement_civic_depth.py` — selective local-justice and civilian-outbreak materialization. Local cases never imply guilt; outbreak compartments review with elapsed time, conserve regional/local population on deaths, and propagate only through exact strategic routes.

`state/civic/justice/index.json` — authority:false routing for exact material local-justice case records under `state/civic/justice/`.

`state/civic/outbreaks/index.json` — authority:false routing for exact active/resolved civilian outbreak records under `state/civic/outbreaks/`.

`runtime/sword_runtime/intrigue_schemes.py` — generic exact intrigue schemes with existing agents, reserved silver, exact access/tools/targets, separate progress/exposure, discovery and bounded terminal effects.

`runtime/sword_runtime/prisoner_system.py` — conserved surrender/custody groups, named captures, guards, food/water, escape review, transfer, parole/release/ransom/recruitment/execution and movement with the exact custodian formation.

`runtime/sword_runtime/family_autonomy.py` — bounded NPC-to-NPC courtship/proposal/betrothal continuity from saved mutual relationship evidence; never invents attraction and never chooses for the player.
