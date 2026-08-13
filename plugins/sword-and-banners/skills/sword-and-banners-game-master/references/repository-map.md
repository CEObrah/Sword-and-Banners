# Repository Map

Use this reference for OOC DEV source-location and authority questions. The machine routing contract is `runtime/contracts/repository-map.json`; this prose explains the important human-facing ownership boundaries.

## Top-level authority

`runtime/`
: Executable Sword engine, command planning, transaction system, causal simulation, API/MCP service, bootstrap, persistence, recovery, and integration.

`game/`
: Static game authority: rules, schemas, mechanics definitions, world content, historical background, locations, routes, institutions, Houses, equipment, economy, and other non-campaign definitions.

`state/`
: Mutable committed campaign truth for the Tang Wei campaign. Records explicitly marked `authority: false` are bounded routing/projection/evidence surfaces and never replace the exact owners they reference.

`plugins/sword-and-banners/skills/sword-and-banners-game-master/`
: Canonical repository source for ChatGPT GM operating/presentation guidance. It is not mechanical campaign authority and a Git commit does not automatically update the installed Skill.

`tests/runtime/`
: Runtime, architecture, security, hostile-input, living-world, interaction, warfare, transaction, replay, and persistence verification.

`tools/`
: Fast verification, focused test routing, Gold diagnostics, migrations, soak gates, and development utilities.

`railway.toml`
: Sole production Railway build/deploy/watch configuration. Runtime/game/dependency/deployment changes redeploy; gameplay state and runtime-neutral Skill/docs/tests/tools/workflow/README changes are excluded from deployment loops.

`docs/RUNTIME_SERVICE_DEPLOYMENT.md`
: Canonical Railway/Auth0/ChatGPT deployment procedure.

## Machine repository map

`runtime/contracts/repository-map.json`
: Active machine-readable development router. Do not recreate the retired `game/data/runtime/` execution tree.

## Runtime entry points

`runtime/sword_runtime/engine.py`
: Baseline domain mechanics, semantic reducers, formation/training/economy/family/warfare behavior, and core planner logic.

`runtime/sword_runtime/service_runtime.py`
: Production runtime wiring, remote durability, non-probing contested/hidden-future preview behavior, player-agency hardening, and hosted planner composition.

`runtime/sword_runtime/living_world.py`
: Bounded non-authoritative operational memory and high-salience wake primitives.

`runtime/sword_runtime/causal_living_world.py`
: Globally chronological causal catch-up, resumable player-facing wake settlement, and causal event provenance.

`runtime/sword_runtime/production_living_world.py`
: Final hosted planner normalizations for assignment/custody, commander availability, physical operation truth, and provenance.

`runtime/sword_runtime/player_group_actions.py`
: Causally parallel grouped player military actions such as multi-formation mobilization and escorted travel; exact formation owners remain authority.

`runtime/sword_runtime/systems/campaign_events.py`
: Bounded short-horizon campaign-event routing. `authority: false` work targets become occurrence truth only when the causal runtime settles them into an exact event-registry owner.

`runtime/sword_runtime/campaign_event_planner.py`
: Hosted planner integration for one-shot campaign-event work, routed institutional follow-ups, recurring world-arc reviews/report routes, fair formation-candidate routing, and resumable player-facing event boundaries.

`runtime/sword_runtime/institutional_processes.py`
: Causal follow-up routing for already-established institutional interactions. It reads bounded `authority: false` process routes and typed player attempts, then settles due responses into the existing exact event-registry authority.

`runtime/sword_runtime/world_arcs.py`
: Causal reviews for the existing exact `arc-registry` authority and delayed player-visible report propagation. It may establish bounded abstract initiatives from exact saved actors/goals but never replaces the exact domain owner of a material consequence.

`runtime/sword_runtime/autonomy_routing.py`
: Rotating bounded candidate windows for large autonomous formation sets so a working-set limit never becomes permanent first-N eligibility.

`runtime/sword_runtime/development.py`
: Exact-person development settlement and skill progression bounds.

`runtime/sword_runtime/command_contracts.py`
: Closed **engine** semantic payload-key contracts. Surface-only `interaction_action` is intentionally not an engine command.

## Player-facing API/MCP

`runtime/sword_runtime/api/operations.py`
: Core player-facing reads and semantic command operations shared by service surfaces.

`runtime/sword_runtime/api/stable_operations.py`
: Production player-safe wrapper. It owns bounded hot-context projection, exact rehydration/paging, stale-scene replacement, typed interaction admission, hiding new raw `scene_consequence` writes, wake-aware availability, and stable low-information failures.

`runtime/sword_runtime/api/interaction_surface.py`
: Surface-only `interaction_action` contract. Validates player-owned target/action/statement/posture/formations, forbids caller-authored NPC/world outcomes, embeds the original surface digest, translates to an attempt-only compatibility record, reads triggered interaction/report handles, and reconstructs safe runtime scene continuity from current owners plus already-triggered facts.

`runtime/sword_runtime/api/mcp.py`
: OAuth/JWT MCP base service, core ChatGPT tools, exact preview attestation, security metadata, and protected-resource metadata.

`runtime/sword_runtime/api/mcp_extensions.py`
: Additive bounded read tools installed by production app wiring: `get_command_contract`, `list_controlled_formations`, `list_known_information`, and `list_interaction_handles`.

`runtime/sword_runtime/api/app.py`
: FastAPI application, health and compatibility REST routes, one production runtime instance, and production MCP mounting/extension installation.

`runtime/sword_runtime/api/world_reference.py`
: Bounded cold reference search. Reference results never prove mutable campaign facts or player knowledge.

`runtime/sword_runtime/bootstrap.py`
: Railway persistent-checkout bootstrap and safe history-replacement recovery.

## Transaction and Git durability

`runtime/sword_runtime/tx/coordinator.py`
: Transaction lifecycle, WAL, commit, remote durability, receipt publication, and recovery.

`runtime/sword_runtime/tx/remote.py`
: Exact configured-branch remote preflight, runtime-neutral fast-forward allowlist, push, and remote verification.

`runtime/sword_runtime/tx/git.py`
: Local Git staging/commit primitives.

`runtime/sword_runtime/tx/wal.py`
: Write-ahead log.

`runtime/sword_runtime/tx/receipts.py`
: Immutable command receipts and idempotent duplicate handling.

`runtime/contracts/transaction-invalidations.json`
: Tombstones for receipted transactions deliberately removed by a diagnosed campaign repair.

## Campaign state anchors

`state/meta.json`
: Campaign ID, player ID, revision, world time, seed.

`state/player.json`
: Tang Wei's active player record.

`state/scene.json`
: Authored player-facing scene projection. It is presentation state only when its time/revision no longer match current campaign authority. Production stable operations then strip transient claims and build a current runtime projection rather than treating old prose as present fact.

`state/runtime.json`
: Authoritative temporal frontier: causal hosts/events and persisted wake state.

`state/arc/kingdom-arcs.json`
: Exact mutable campaign-scale arc/pressure authority. Active records may be routed into recurring causal review; dormant historical possibilities remain conditional and are not activated by date alone.

`state/index/owner-index-gold.json`
: Active exact owner routing for mutable campaign objects.

`state/index/location-formation-index.json`
: Non-authoritative exact-location routing for formations; exact formation documents remain authority.

`state/index/commander-formation-index.json`
: Non-authoritative commander-to-formation routing; exact people/formations remain authority.

`state/index/campaign-causal-work.json`
: Optional bounded `authority: false` routing for explicit short-horizon campaign work. A pending target is not proof an event occurred.

`state/index/institutional-process-routing.json`
: Bounded `authority: false` trigger/delay routing for institutional follow-ups. It never proves that a response occurred; only the settled exact event-registry record does.

`state/event/*.json`
: Exact mutable event/message/movement owners. Triggered campaign occurrences are authoritative here after runtime settlement.

`state/information/index.json`
: Routing index for exact information claims. Player knowledge is revalidated from each claim's saved `knowers`; an omitted hot-window claim is not forgotten.

`state/formations/*.json`
: Persistent exact formations. The ordinary play context is a bounded recent/current window; omitted controlled formations can be rediscovered by the paged read surface and revalidated from exact authority.

`state/world/operational-memory.json`
: Bounded `authority: false` operational evidence when present. It never replaces exact formation, person, operation, battle, or state authority.

`state/relationships-gold.json`
: Active relationship authority.

Never infer that every state file is player-visible. Bounded operations enforce the knowledge boundary.

## Testing and release verification

`tools/quick_check.py`
: Fast syntax plus structural production-audit gate for normal development.

`tools/test_changed.py`
: Changed-path router for the maintained focused regression slice.

`tools/audit_gold.py`
: Structural production audit used by the quick gate.

`tools/run_gold_suite.py`
: Deliberate broad Gold diagnostic/release runner. It is not required for every ordinary edit.

`tools/run_gold_soak_gate.py`
: Long persistence soak for concrete release/diagnostic needs.

`tests/runtime/test_interaction_surface.py`
: Typed attempt, outcome-injection, digest/idempotency, bounded interaction-handle paging, raw-scene bypass, and stale-projection continuation regressions.

`tests/runtime/test_world_arcs.py`
: Active-arc scheduler registration, exact saved-goal initiative, event-schema parity, deterministic review, hidden/report knowledge separation, and rotating-candidate fairness regressions.

`tests/runtime/test_institutional_processes.py`
: Current-campaign regression that a completed Ouki review withdrawal arms a causal follow-up and that the settled response validates against the canonical event schema.

`tests/runtime/test_architecture_service.py`
: Service architecture, player-safe context, scene projection, MCP/deployment-file, and integration invariants.

`tests/runtime/test_stable_operations.py`
: Stable player-facing wake and failure-surface behavior.

Prefer state-independent fixtures for invariant logic. Keep evolving-current-campaign integration as a separate disposable-copy layer.

## Canonical documentation rule

The Game Master Skill is the canonical ChatGPT-facing operating/development manual. `references/world-arcs.md` documents the campaign-scale arc rules. Do not recreate root `VOICE.md`, `PLAYER_INTERFACE.md`, `RUNTIME.md`, `REPOSITORY_MAP.md`, `AGENTS.md`, or `DEPLOYMENT.md` copies. Keep root `README.md` as orientation only and deployment procedure under `docs/`.
