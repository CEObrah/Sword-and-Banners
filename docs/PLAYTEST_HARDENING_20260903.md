# Sword & Banners Playtest Hardening — 2026-09-03

This pass is driven by observed gameplay failures, not release-gate counts. Structural checks remain smoke tests; acceptance is the replay of player-facing failures and their analogous subsystem risks.

## Implemented behavior

- Campaign-scale force presentation now uses peer operational echelons. Tang Wei's 9,500 are represented as three primary commands (High Guard 4,500; Black Banner 4,000; Red Lance 1,000) with nineteen 500-person tactical leaves retained underneath for casualties, frontage, resupply, and local battle mechanics.
- Operational battlefields now default to terrain/force-derived variable geometry instead of a fixed three/five-slot abstraction. Force scale controls frontage/depth; registered terrain selects open-field, broken-hill, wooded-hill, mountain, river/floodplain, fortified-pass, or fortified-site archetypes.
- Generated front sectors carry explicit operational objectives (central frontage, heights, passes, crossings, wooded corridors, siege approaches, etc.). These are mission targets only; they do not create casualties, territory, sovereignty, or automatic battle victory.
- Primary operational commands deploy coherently. Their leaf formations are not round-robin scattered across the map. A command can receive one battlefield order or timed redeployment while each leaf remains an exact conserved formation underneath.
- Battle-command planning layers missions over physical deployment rather than teleporting forces into newly selected sectors.
- Campaign march remains plan -> exact order -> scheduler host -> elapsed physical movement. The revision-7 standing hold can cross autonomous march frontiers and commit normally.
- Battle-command supply and pressure rule failures now fail closed instead of silently substituting neutral values.
- Personal-combat results expose exact-person accounting; formation battle keeps aggregate casualty accounting separate from personal takedowns.
- Closed-schema/runtime-write parity regressions cover the operational battlefield and operation owners.

## Mutable-save test repair

`test_campaign_march_lifecycle.py` no longer assumes the campaign is still at its historical starting positions with zero march hosts. Each test creates an isolated pre-execution fixture by removing only campaign-march lifecycle outputs inside its disposable clone, preserving current formation locations, campaign authority, and unrelated truth. This makes the tests valid on a matured save without rewinding the campaign.

## Cross-game analogous audit

The same recurring failure classes were reviewed in Shinobi independently: silent compound-intent loss, plan-without-execution, misleading projections, optional-read swallowing, physical-presence confusion, and player-facing recovery coupling. Repairs are implemented separately in each repository; there are no cross-game runtime imports or shared state.

## Verification actually run

Behavior regressions passed locally:

- `test_battlefield_scale_model.py` — 3 passed
- `test_play_failure_matrix.py` — 2 passed
- `test_play_regression_hardening.py` — 5 passed
- `test_closed_schema_runtime_write_parity.py` + `test_preview_execute_schema_parity.py` — 7 passed
- `test_semantic_wait_policy.py` — 2 passed
- `test_campaign_march_lifecycle.py` — 7 passed after mutable-save fixture repair
- `tools/quick_check.py` — PASS (1,395 JSON files parsed; 236 registered schemas validated)

The broad changed-file gate was also started and produced passing progress, but exceeded the per-command execution window; that timeout is not counted as a pass. Focused play regressions above are the acceptance evidence for this build.

## Campaign truth

No Sword campaign state/time/revision was rewritten by this OOC development pass. Transient test caches, bytecode, backup/orig files, and private runtime scratch are excluded from the playtest package.

This build is hardened against the failures above; it is not a claim that no undiscovered gameplay bug remains.
