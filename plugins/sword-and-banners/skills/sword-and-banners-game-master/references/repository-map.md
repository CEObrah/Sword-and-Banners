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

`runtime/sword_runtime/house_tang_development.py` — House Tang/Sword Manor aggregate development, lawful intake, and aggregate rank progression.

`runtime/sword_runtime/cohort_tx_support.py` — formation training isolation and exact/person-lite materialization from already conserved cohort slots.

`runtime/sword_runtime/development.py` — exact/person-lite development and combat-experience settlement.

`runtime/sword_runtime/living_world.py`, `causal_living_world.py`, `production_living_world.py` — bounded causal scheduling, wakes, and production settlement.

`runtime/sword_runtime/systems/campaign_events.py`, `campaign_event_planner.py`, `institutional_processes.py`, `world_arcs.py` — event/front/institutional causal work and report routing.

`runtime/sword_runtime/vitality.py` — read-only playability/causal-throughput diagnostics.

`runtime/sword_runtime/civil_world.py` — production causal bridge for private production, exact capital markets/scarcity pricing, funded/cancellable institution projects, sourced granary procurement, differentiated knowledge-gated faction actions, evidence-gated world-arc actor/domain dispatch, dynamic interstate front discovery, weighted local-site projections, conserved occupation revolts, House-polity progression, recognized-polity institutions/monthly autonomy/shared interstate fronts, autonomous irregular revolt routing, and occupation/governance integration. It does not replace exact state, market, institution, faction, polity, territory, treasury, population, force, or private-economy owners.

`game/data/mechanics/civil-economy.json` — canonical aggregate civil production, project-input, market-normal-stock, House estate, granary procurement, and occupation integration parameters.

`state/economy/merchant-houses.json` — exact mutable registry for named merchant-house capital, credit policy, conserved loans, repayments, and provenance. It is capital/credit authority, not a substitute for physical market stock or private-economy commodity ownership.

`state/contract/tang-supply-contracts.json` — House Tang material supply-contract terms. Production settlement realizes deliveries through exact source depots/private economy and records shortfall rather than materializing missing food or fodder.

`state/contract/tang-contracted-defense.json` — House Tang contracted-defense membership and payment authority. Runtime reconciles member company headcount from exact mercenary owners and transfers real treasury payment into those company treasuries.

`game/data/politics/faction-profiles.json` — canonical differentiated starting goals/resources/action vocabularies for autonomous faction owners.


`runtime/sword_runtime/player_group_actions.py` — causally parallel grouped player military actions.

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

`state/history/events/index.json` — bounded authoritative semantic-history head and archive routing. `runtime/sword_runtime/history_store.py` spills older exact events into `state/history/events/archive/*.json`; archive segments remain exact history and are rehydrated only when needed.

`state/politics/treaties.json` — first-class exact interstate treaty/ceasefire authority. Military control never silently resolves legal claim; settlement terms, truce horizon, parties, territorial status, and provenance live here and are linked from state diplomacy.

`state/factions/*.json` — mutable exact faction agendas/resources/relationships/knowledge windows. Independent powers such as the northern steppe confederation require their own exact faction owner rather than being routed through another polity.

`runtime/sword_runtime/causal_event_store.py` — bounded causal-event hot head, exact archive segments, deterministic hash-route shards, and archive-aware discovery for player-facing reports. Archive metadata is a bounded window and never the authority for archived event existence.

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
