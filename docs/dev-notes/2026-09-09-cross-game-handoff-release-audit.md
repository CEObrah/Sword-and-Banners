# 2026-09-09 Cross-game handoff and release-state audit

## Original defect

Game: Sword & Banners
Subsystem: campaign-command upward-report projection / GM scene handoff
Severity: systemic P1 playability defect

The campaign owner could retain a valid response-bearing outbound report while a later compact projection selected only the chronologically newest pending rows. Under sufficient later traffic, the older request disappeared from GM context. A second inverse defect allowed delivered history to be relabeled as pending by compact command projection. A route-unresolved report could also be mislabeled as physically in flight.

## Sword repair

- Added one shared pending-report selector used by campaign owner projection, command compaction, and GM scene compaction.
- Priority is response-bearing unresolved work, then material unresolved work, then routine unresolved traffic.
- Delivered history is projected separately and never becomes pending work.
- `route_unresolved` remains visible as unresolved persistence but explicitly reports `outbound_report_in_flight: false` and must not be waited on as if delivery were scheduled.
- Added regressions for old response-bearing requests hidden by newer traffic, delivered-history false positives, and route-unresolved false in-flight claims.

Verification actually run in the local uploaded ZIP workspace included the dedicated remote-command suite, campaign command lifecycle/delivery/wait suites, Qin starvation/arrival regressions, and release/Skill/cross-game contract tests. No campaign-state mutation was used.

## Cross-game analogue: Shinobi

Checked: delayed event handoffs, semantic waiting, scene open-thread projection, compact interaction history, and exact thread demand-load path.

Result: the Sword defect did not reproduce. Shinobi does not compact a durable outbound courier list through the same multi-tail pipeline. Interrupting delayed events use authoritative event-seeking boundaries; active response-bearing scene waits are represented by open-thread state with count/truncation signals and an exact `scene_open_threads` retrieval path. Existing semantic-wait and scene-session regressions passed. No Shinobi handoff runtime change was made.

## Packaging/release defect found in both games

Severity: systemic P1 deployment/release defect.

Neither repository bound a release candidate to the exact intended mutable campaign snapshot. A source-fixed build could therefore be packaged with an older but internally valid save and still pass ordinary mechanics/schema checks. This is the defect class that allowed Shinobi revision 106 to reappear after a full-fresh revision-97 repair had already existed.

Repair in both repositories:

- Added a release campaign-state contract containing campaign identity, revision, world time, and deterministic state-tree digest.
- Added a release-state verifier.
- Wired the verifier into the maintained release path.
- Added adversarial tests proving a stale revision/state copy is rejected.
- Shinobi additionally pins the exact fresh combat baseline: active 12-v-18 encounter, zero elapsed combat, all combatants fresh, player Qi/loadout, and zero interaction/scene-history records.

Campaign truth in the delivered workspaces remained unchanged while implementing these source/release checks.

## QA harness note

Sword's `test_command_staff_continuity.py` assertions pass, but explicit `--basetemp` lifecycle can spend disproportionate time in temporary Git-backed clone teardown under constrained hosts. Standalone isolated execution of the complete module passed. The release tooling records this as harness behavior rather than a gameplay assertion failure.
