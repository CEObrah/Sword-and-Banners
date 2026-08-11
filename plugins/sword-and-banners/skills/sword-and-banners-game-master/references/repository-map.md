# Repository Map

Use this reference for OOC DEV source location and authority questions.

## Top-level authority

`runtime/`
: Executable Sword engine, command planning, transaction system, API/MCP service, bootstrap, persistence, recovery, and production integration.

`game/`
: Static game authority: rules, schemas, mechanics definitions, world content, historical background, locations, routes, institutions, Houses, equipment, economy, and other non-campaign definitions.

`state/`
: Mutable committed campaign truth for the active Tang Wei campaign. Some saved routing/projection records inside `state/` explicitly declare `authority: false`; those are evidence or indexes, not replacement authorities for the exact owners they reference.

`plugins/sword-and-banners/skills/sword-and-banners-game-master/`
: ChatGPT GM operating and presentation Skill. It is not mechanical campaign authority.

`tests/runtime/`
: Runtime, architecture, hostile-input, warfare, living-world, acceptance, transaction, and long-horizon verification.

`tools/`
: Gold audit, migrations, soak gates, and development utilities.

`.github/workflows/audit.yml`
: Mandatory Gold CI release gate.

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
: Core deterministic command planner/runtime mechanics and baseline domain reducers.

`runtime/sword_runtime/living_world.py`
: Bounded autonomous operational memory, objective-fit formation scoring, concurrent state-response planning, and learned battlefield evidence. This layer does not replace exact formations, people, operations, states, or Houses as authority.

`runtime/sword_runtime/causal_living_world.py`
: Production chronological causal scheduling, callback-created-host preservation, resumable high-salience interstate contact wakes, and autonomous battle provenance.

`runtime/sword_runtime/production_living_world.py`
: Final hosted living-world integrity layer: hard formation reservation, exact commander/readiness requirements, operation status truthfulness, and production provenance normalization.

`runtime/sword_runtime/command_contracts.py`
: Closed semantic command payload-key contracts.

`runtime/sword_runtime/service_runtime.py`
: Production runtime wiring, required remote Git durability, hidden contested/future preview readiness, player-neutral campaign identity, and pending-wake preview enforcement.

`runtime/sword_runtime/api/operations.py`
: Core bounded player-facing operations shared by REST and MCP.

`runtime/sword_runtime/api/stable_operations.py`
: Production low-information failure classification and player-visible pending-wake/temporary-command availability projection.

`runtime/sword_runtime/api/app.py`
: FastAPI application, health, compatibility REST routes, one production runtime instance, optional MCP mounting.

`runtime/sword_runtime/api/mcp.py`
: OAuth/JWT MCP service, six ChatGPT tools, preview attestation, security metadata, protected-resource metadata.

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

## Campaign state anchors

`state/meta.json`
: Campaign ID, player ID, revision, world time, seed.

`state/player.json`
: Tang Wei's active player record.

`state/scene.json`
: Current player-facing scene projection and unresolved decision context.

`state/runtime.json`
: Autonomous causal hosts, scheduler/runtime campaign state, and any persisted high-salience wake boundary.

`state/world/operational-memory.json`
: Lazily created bounded `authority: false` operational-memory projection. It records evidence used by autonomous assignment but never replaces exact formation, commander, battle, operation, state, relationship, reputation, or logistics authority.

`state/index/owner-index-gold.json`
: Active owner routing for mutable campaign objects.

`state/relationships-gold.json`
: Active relationship authority.

Do not infer that every state file is player-visible. MCP bounded reads enforce the knowledge boundary.

## Gold verification

`tools/run_gold_suite.py`
: Main production verification runner.

`tools/audit_gold.py`
: Static production invariants.

`tools/run_gold_soak_gate.py`
: Mandatory long-run soak gate.

`tests/runtime/test_living_world_intelligence.py`
: Learned autonomy, resumable wake, House-development ownership, hard progression bound, causal provenance, and deterministic disposable current-campaign replay.

`tests/runtime/test_production_living_world.py`
: Final assignment-integrity, commander-availability, physical operation readiness, and production provenance regressions.

`tests/runtime/test_stable_operations.py`
: Stable failure classification and truthful pending-wake command-availability surface.

The Gold suite includes architecture/service, transaction, repair hardening, long-horizon, acceptance, semantic surface, hostile/adversarial inputs, warfare, living-world intelligence, current-campaign deterministic replay, and mandatory persistence soak.

## Canonical documentation rule

The Game Master Skill is the canonical ChatGPT-facing operating and development manual. Do not recreate root `VOICE.md`, `PLAYER_INTERFACE.md`, `RUNTIME.md`, `REPOSITORY_MAP.md`, `AGENTS.md`, or `DEPLOYMENT.md` copies. Keep root `README.md` as orientation only and keep deployment procedure under `docs/`.
