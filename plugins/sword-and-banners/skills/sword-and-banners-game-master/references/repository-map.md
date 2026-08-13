# Repository Map

Use this reference for OOC DEV source location and authority questions.

## Top-level authority

`runtime/`
: Executable Sword engine, command planning, transaction system, API/MCP service, bootstrap, persistence, recovery, production living-world intelligence, and integration.

`game/`
: Static game authority: rules, schemas, mechanics definitions, world content, historical background, locations, routes, institutions, Houses, equipment, economy, and other non-campaign definitions.

`state/`
: Mutable committed campaign truth for the active Tang Wei campaign. Persisted records explicitly marked `authority: false` are bounded projections/evidence/routing and do not replace the exact owners they reference.

`plugins/sword-and-banners/skills/sword-and-banners-game-master/`
: ChatGPT GM operating and presentation Skill. It is not mechanical campaign authority.

`tests/runtime/`
: Runtime, architecture, hostile-input, warfare, living-world, acceptance, transaction, current-campaign replay, and long-horizon verification.

`tools/`
: Gold audit, migrations, soak gates, release verification, and development utilities.

`.github/workflows/audit.yml`
: Lightweight path-filtered automatic smoke CI plus deliberate manual full-Gold entry point. Do not turn every commit into the complete soak/release suite.

`railway.toml`
: Sole production Railway build/deploy/watch configuration.

`docs/RUNTIME_SERVICE_DEPLOYMENT.md`
: Canonical Railway/Auth0/ChatGPT deployment procedure.

## Machine repository map

The active machine-readable repository routing contract is:

`runtime/contracts/repository-map.json`

Do not recreate the retired `game/data/runtime/` directory. Gold explicitly treats that old execution tree as retired.

## Runtime entry points

`runtime/sword_runtime/engine.py`
: Baseline domain mechanics, semantic reducers, formation/training/economy/family/warfare behavior, and core planner logic.

`runtime/sword_runtime/living_world.py`
: Bounded non-authoritative operational memory, objective-fit exact formation selection, concurrent state-response capacity, learned operational evidence, and high-salience wake primitives.

`runtime/sword_runtime/causal_living_world.py`
: Globally chronological causal catch-up, callback-created host preservation, resumable player-facing wake settlement, autonomous battle provenance, and cross-host chronological consistency.

`runtime/sword_runtime/production_living_world.py`
: Final hosted planner normalizations: hard assignment/custody exclusion, exact commander availability, truthful physical operation status, and provenance normalization.

`runtime/sword_runtime/player_group_actions.py`
: Causally parallel grouped player military actions such as multi-formation mobilization and escorted travel; exact formation owners remain military authority.

`runtime/sword_runtime/systems/campaign_events.py`
: Bounded short-horizon campaign-event routing. It materializes `authority: false` work targets into the existing causal frontier and settles due targets only into exact event-registry owners.

`runtime/sword_runtime/campaign_event_planner.py`
: Hosted planner layer that integrates one-shot campaign-event work with chronological catch-up and resumable player-facing event boundaries.

`runtime/sword_runtime/development.py`
: Exact-person development settlement and absolute skill progression bound.

`runtime/sword_runtime/command_contracts.py`
: Closed semantic command payload-key contracts.

`runtime/sword_runtime/service_runtime.py`
: Production runtime wiring, required remote Git durability, non-probing contested/hidden-future preview behavior, and production planner composition.

`runtime/sword_runtime/api/operations.py`
: Core bounded player-facing operations shared by REST and MCP.

`runtime/sword_runtime/api/stable_operations.py`
: Stable player-safe operation wrappers, wake-aware command availability, and low-information error mapping.

`runtime/sword_runtime/api/app.py`
: FastAPI application, health, compatibility REST routes, one production runtime instance, optional MCP mounting.

`runtime/sword_runtime/api/mcp.py`
: OAuth/JWT MCP service, ChatGPT tools, preview attestation, security metadata, and protected-resource metadata.

`runtime/sword_runtime/bootstrap.py`
: Railway persistent-checkout bootstrap and safe history-replacement recovery.

## Transaction and Git durability

`runtime/sword_runtime/tx/coordinator.py`
: Transaction lifecycle, WAL, commit, remote durability, receipt publication, and recovery.

`runtime/sword_runtime/tx/remote.py`
: Exact configured-branch remote preflight, push, and remote verification.

`runtime/sword_runtime/tx/git.py`
: Local Git staging/commit primitives.

`runtime/sword_runtime/tx/wal.py`
: Write-ahead log.

`runtime/sword_runtime/tx/receipts.py`
: Immutable command receipts and idempotent duplicate handling.

`runtime/contracts/transaction-invalidations.json`
: Explicit tombstones for receipted transactions deliberately removed by a diagnosed campaign repair.

## Campaign state anchors

`state/meta.json`
: Campaign ID, player ID, revision, world time, seed.

`state/player.json`
: Tang Wei's active player record.

`state/scene.json`
: Player-facing scene projection and unresolved decision context. It is valid only when its projection revision/time match current campaign authority.

`state/runtime.json`
: Authoritative temporal frontier: autonomous causal hosts, scheduler/runtime campaign state, and bounded persisted wake state.

`state/index/campaign-causal-work.json`
: Optional bounded `authority: false` routing for explicit short-horizon campaign work. A pending target here is not proof an event occurred and is not a second event authority. When the causal runtime settles a due target, the occurrence is written into its exact routed `state/event/` owner; overdue repair targets catch up at the current world time rather than rewinding history.

`state/event/*.json`
: Exact mutable event/message/movement owners. Causally triggered campaign occurrences become authoritative here only after runtime settlement.

`state/index/owner-index-gold.json`
: Active owner routing for mutable campaign objects.

`state/index/operational-memory.json`
: Bounded `authority: false` operational evidence for autonomous selection and history when present. It never replaces exact formation, person, operation, battle, or state authority.

`state/relationships-gold.json`
: Active relationship authority.

Do not infer that every state file is player-visible. MCP bounded reads enforce the knowledge boundary.

## Testing and release verification

Routine pushes do not need the complete release suite.

`.github/workflows/audit.yml`
: Runs fast automatic smoke checks only when relevant runtime/game/tools/tests/config paths change. Skill/docs/state-only commits do not need to spend CI on the full suite.

`tools/audit_gold.py`
: Structural production audit. Included in automatic smoke.

`tools/run_gold_suite.py`
: Full deliberate Gold production verification runner. Use for major releases, substantial runtime changes, pre-deployment hardening, and explicit Gold certification.

`tools/run_gold_soak_gate.py`
: Long persistence soak used by the full Gold gate, not by every routine commit.

`tests/runtime/test_living_world_intelligence.py`
: Living-world intelligence, high-salience wake, progression-bound, exact/aggregate and current-campaign replay coverage.

`tests/runtime/test_production_living_world.py`
: Hosted planner assignment/custody/provenance invariants, including short-horizon campaign causal-work settlement.

`tests/runtime/test_stable_operations.py`
: Stable player-facing wake and error-surface behavior, including ordinary responses to one-shot campaign-event boundaries.

Prefer state-independent fixture regressions for invariant logic. Keep evolving-current-campaign replay as a separate integration layer on disposable copies.

## Canonical documentation rule

The Game Master Skill is the canonical ChatGPT-facing operating and development manual. Do not recreate root `VOICE.md`, `PLAYER_INTERFACE.md`, `RUNTIME.md`, `REPOSITORY_MAP.md`, `AGENTS.md`, or `DEPLOYMENT.md` copies. Keep root `README.md` as orientation only and keep deployment procedure under `docs/`.
