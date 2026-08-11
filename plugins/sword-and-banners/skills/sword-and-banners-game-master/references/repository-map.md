# Repository Map

Use this reference for OOC DEV source location and authority questions.

## Top-level authority

`runtime/`
: Executable Sword engine, command planning, transaction system, API/MCP service, bootstrap, persistence, recovery, and production integration.

`game/`
: Static game authority: rules, schemas, mechanics definitions, world content, historical background, locations, routes, institutions, Houses, equipment, economy, and other non-campaign definitions.

`state/`
: Mutable committed campaign truth for the active Tang Wei campaign.

`plugins/sword-and-banners/skills/sword-and-banners-game-master/`
: ChatGPT GM operating and presentation Skill. It is not mechanical campaign authority.

`tests/runtime/`
: Runtime, architecture, hostile-input, warfare, acceptance, transaction, and long-horizon verification.

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
: Core command planner/runtime mechanics.

`runtime/sword_runtime/command_contracts.py`
: Closed semantic command payload-key contracts.

`runtime/sword_runtime/service_runtime.py`
: Production runtime wiring, required remote Git durability, and non-probing contested preview readiness.

`runtime/sword_runtime/api/operations.py`
: Bounded player-facing operations shared by REST and MCP.

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
: Autonomous causal hosts and scheduler/runtime campaign state.

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

The Gold suite includes architecture/service, transaction, long-horizon, acceptance, semantic surface, hardening, adversarial parity, hostile-command matrix, and warfare tests.

## Canonical documentation rule

The Game Master Skill is the canonical ChatGPT-facing operating and development manual. Do not recreate root `VOICE.md`, `PLAYER_INTERFACE.md`, `RUNTIME.md`, `REPOSITORY_MAP.md`, `AGENTS.md`, or `DEPLOYMENT.md` copies. Keep root `README.md` as orientation only and keep deployment procedure under `docs/`.
