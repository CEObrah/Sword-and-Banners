# Final Cross-Game Architecture Audit and Repair

Date: 2026-09-02

Scope: Shinobi RPG and Sword & Banners packaged repositories supplied for the final audit. This report records source inspection, targeted verification, confirmed repairs, measured context behavior, and remaining risks. It does not claim any test that was not actually run.

## A. Executive architecture assessment

The overall architecture is correct for this class of persistent AI-narrated RPG:

```text
Player
  -> ChatGPT conversation / Project continuity
  -> GM Skill procedure and scene doctrine
  -> bounded MCP reads and semantic mechanic discovery
  -> Railway-hosted authoritative runtime
  -> deterministic mechanics + persistent campaign truth
  -> transaction / chronology / scheduler / durability
  -> bounded refreshed context and committed result
  -> ChatGPT scene direction, dialogue, pacing, and narration
  -> Player
```

The repositories already implement the most important division well. Runtime code owns hard truth and consequences. The Skills explicitly treat the command catalog as a consequence toolkit rather than turn structure. Formal scene sessions are presentation continuity, not physical authority. Exact presence is revalidated. GM-private truth is explicitly backstage and does not automatically become player knowledge. MCP exposes compact mechanic families and demand-loads exact command contracts.

The audit therefore did not replace the architecture. It removed a production-only historical repair dependency in Shinobi, repaired Sword regression routing and stale mercenary fixtures, and reduced repeated static GM doctrine in the Sword MCP hot packet.

No confirmed P0 campaign-corruption defect was found in the inspected paths. No architectural reason was found to move storytelling into Python or to move hard mechanics back into the LLM.

## B. Actual authority and information map

| Concern | Authoritative owner | Non-authoritative projection / consumer |
|---|---|---|
| Campaign revision and world time | `state/meta.json` plus transaction/scheduler authority | Chat/Project memory, narration |
| Hard mechanical consequences | Runtime reducers/planners under `runtime/` | Skill prose, MCP descriptions |
| Transaction atomicity/idempotency | Transaction coordinator, WAL, receipt store, Git durability | API/MCP response envelope |
| Physical person presence | Exact person plus travel/custody/combat owners and canonical presence resolver | `state/scene.json`, scene sessions |
| Scene lifecycle and prose | ChatGPT GM under Skill procedure | Scene session persistence only |
| Player knowledge | Player-visible projections and information owners | GM-private cognition is not player knowledge |
| GM-private direction | Explicit bounded `gm_private*` scene/cognition packets | Never mechanical authority |
| Command discoverability | MCP mechanic-family index -> one family -> one contract | Repository implementation details |
| Static rules/world data | `game/`, schemas, static repository data | Runtime projections |
| Source/deployment history | GitHub source and deployment configuration | Not live campaign truth |
| Live campaign durability | Railway runtime checkout plus private WAL/receipts and configured Git durability | Source branch alone is insufficient |

The key invariant remains: `state/scene.json`, open sessions, indexes, read hints, and other projections cannot grant physical presence, money, command authority, equipment, injury, relationship change, or other durable truth.

## C. Cross-game comparison and conceptual parity

| Subsystem | Shinobi approach | Sword approach | Stronger current pattern | Conceptual port / repair conclusion |
|---|---|---|---|---|
| Transactions | Exact revision, preview, WAL/receipt, Git staging, recovery | Same core model with deployment attestation and hardened recovery tests | Tie | Keep isolated implementations; preserve the shared invariant set |
| Production startup | Transition-aware operations plus combat-span wrapper; previously also installed rev143 repair anchor | Clean production runtime plus deployment compatibility check | Sword | Shinobi production no longer installs the historical repair anchor |
| Scheduler observability | Compact recurring/one-off scheduler and causal settlement | Explicit host/event registry with coverage, dirty flags, overdue diagnostics | Sword | Shinobi should continue borrowing observability concepts, not Sword state structures |
| Context size | Very compact current handoff, large contract-discovery component | Richer command/warfare handoff, larger controlled-operation component | Shinobi for size; Sword for campaign-command detail | Sword static doctrine was compacted; both retain exact demand loading |
| Scene lifecycle | Strong exact-presence revalidation and presentation-only sessions | Same principle with explicit scene-direction workspace | Tie | Maintain parity without cross-imports |
| NPC scene support | GM-private relationship cognition and present-person direction | GM-private present-person context plus campaign/court context | Tie | Skills already encode the same LLM-first scene principle independently |
| Representation scale | Very large persistent martial population with hydrated/sharded rosters | Cohort-first military scale plus exact named/person-lite materialization | Sword for mass warfare; Shinobi for persistent martial identity | Preserve domain-specific scale; do not homogenize |
| Personal combat | Exact combat, Qi/poison/injury, deterministic physical authority | Exact personal combat with contact physics/anatomy | Tie by domain | Keep mechanics domain-specific; LLM owns choreography around committed outcomes |
| Large warfare | Institutional/mission operations but not the game's focus | Deep formations, battlefields, siege, logistics, campaign command | Sword | No need to copy mass-warfare complexity into Shinobi |
| Contracts/mercenaries | Public contract discovery and exact inspect | Mercenary company contracts plus tactical materialization and cold aggregation | Different domains | Sword regression now proves exact cold -> tactical -> cold conservation |
| Information modeling | Strong player-visible vs GM-private separation | Strong player-visible vs GM-private separation plus reconnaissance/campaign intelligence | Tie | Preserve bounded private truth and exact public delivery |
| Deployment/recovery | Strong, but retained historical production composition debt | Strong deployment attestation and bootstrap isolation | Sword | Shinobi historical anchor removed from production; generic repair remains |

## D. Feature matrix

Status is based on current source trace plus focused evidence in this audit. `Working` does not imply that every long-horizon release/soak suite was rerun.

### Shinobi RPG

| Feature | Status | Evidence / note |
|---|---|---|
| Semantic MCP mechanic discovery | Working | Compact family catalog and exact contract demand loading |
| Revision / preview / execute flow | Working | Release, preview, transaction, invariant tests |
| WAL / receipt / crash recovery | Working | Crash-recovery and changed-owner tests |
| Scene lifecycle | Working | Session is presentation-only; LLM decides begin/continue/end |
| Physical presence | Working | Canonical exact presence tests passed |
| GM-private vs player knowledge | Working | Explicit private cognition/director packets and redaction boundary |
| Exact martial people and roster scale | Working | 11,836 exact people; state ownership and no-op round-trip checks pass |
| Factions / Houses / institutional authority | Working | Current state and world invariant coverage |
| Contracts | Working | Player-safe discovery plus exact inspection path; 14 live visible offers in measured context |
| House/institutional missions | Working | Persistent mission owners and compact player handoff |
| Markets/economy | Working | Scheduler/economy and state ownership checks |
| Training / progression / cultivation | Working | Mature subsystem and maintained tests; no campaign time advanced by audit |
| Poison / injury / recovery | Working | Registered martial mechanics present and integrated with combat |
| Personal/team combat | Working, with composition debt | Core mechanics are deterministic; production still uses a bounded combat-span wrapper that should eventually be integrated generically |
| Travel / chronology | Working | Exact presence and causal time paths are integrated |
| Scheduler / autonomous world work | Working | 4 recurring + 45 one-off current scheduler entries; 99 focused living-world tests passed |
| Family / relationships / social state | Working | Family/relationship state and social-causality tests |
| Government / politics / diplomacy | Working | Dedicated state and source paths exist; not exhaustively re-soaked here |
| Tournaments | Working | Dedicated runtime/state paths present |
| Illness/disease as a broad first-class life system | Partial / weakly evidenced | Source signals are sparse relative to injury/recovery; roadmap candidate, not a confirmed defect |
| Rev143 historical repair anchor | Legacy, forensic only after repair | Helper retained for incident verification, removed from production startup |

### Sword & Banners

| Feature | Status | Evidence / note |
|---|---|---|
| Semantic MCP mechanic discovery | Working | Family -> exact command contract pattern |
| Revision / preview / execute flow | Working | Core transaction tests passed |
| WAL / receipt / recovery | Working | Recovery-hardening tests passed |
| Deployment/bootstrap compatibility | Working | Branch bootstrap and deployment attestation tests passed |
| Scene lifecycle / NPC initiative | Working | Open-world GM, interaction, household, scene tests passed |
| Physical presence and access | Working | Interaction surface requires exact presence or lawful remote channel |
| Knowledge / reconnaissance separation | Working | GM-private and player-safe transport are separate |
| Population/cohort/person materialization | Working | Cohort-first conserved representation and exact-person escalation |
| Formations / command groups | Working | Current context exposes bounded controlled formations/groups |
| Personal combat | Working | Exact physical resolver architecture; focused tests existed and were inspected, not fully rerun as one suite here |
| Battles / battlefields / siege | Working | Dedicated authoritative subsystems and maintained tests |
| Logistics / supply / ammunition | Working | Dedicated authoritative subsystems and state |
| Mercenary ecology | Working after QA repairs | Live contracts and scheduler routes match; tacticalization/cold aggregation tests pass |
| Prisoners / custody | Working | Dedicated prisoner regression passes |
| Campaign command / operations | Working | Current operation projection and planning tests pass |
| Scheduler / living world | Working | 403 hosts, 403 events, coverage complete, dirty=false; 18 focused tests passed |
| Politics / offices / treaties / diplomacy | Working | Deep dedicated state/runtime coverage |
| Family / relationships / life progression | Working | Broad subsystem coverage; not every life-cycle edge was re-soaked |
| Training / officer development | Working | Mature dedicated systems |
| Economy / treasury / markets | Working | Dedicated systems and living-world integration |
| Desertion as a rich first-class personnel system | Partial / weakly evidenced | Source footprint is much smaller than prisoner/wounded/logistics paths; roadmap candidate |
| Context progressive loading | Working, still heavy | Production composite reduced to 47,506 bytes; campaign operation detail remains largest hot contributor |

No major runtime feature was confirmed as `Implemented but unreachable` in the inspected command-family paths. No major core feature was confirmed as `Surface-only`. Where this audit did not run the deeper release/soak suite, the limitation is stated rather than silently promoted to proof.

## E. Defect register

| Severity | Game | Subsystem | Actual cause | Player / engineering impact | Repair | Other game checked? | Verification |
|---|---|---|---|---|---|---|---|
| P2 | Shinobi | Production composition / historical repair | `campaign_entrypoint.py` installed a closed rev143 incident-specific repair anchor that requires legacy Git/WAL evidence absent from a fresh current recovery store | Production carried obsolete campaign-specific Git/WAL coupling and a one-off remote historical path | Removed installer import/call from production entrypoint; retained forensic helper and closed tests | Yes, no analogous Sword production anchor found | 52 focused startup/recovery tests, then quick check + 80 changed-owner checks |
| P2 | Sword | Audit regression | Test hard-coded 62 live mercenary contracts although canonical state legitimately evolved to 12 live obligations | False audit failure and pressure to mutate correct state to satisfy stale history | Replaced cardinality with exact equality between live obligations and scheduler hosts | Shinobi analogous principle checked conceptually | `test_second_order_audit_repairs.py` passes; included in 45-test merc/prisoner batch |
| P2 | Sword | Changed-path QA routing | `tools/test_changed.py` did not map mercenary/prisoner owner files to dedicated regressions | Future edits could bypass the exact subsystem tests they affect | Added `MERCENARY_TESTS` and `PRISONER_TESTS` routing | Shinobi changed-owner gate already selected domain-specific regressions for its edit | Selector inspected; every selected current module passed in isolated batches |
| P2 | Sword | Mercenary regression fixtures | Tests referenced `merc.regional.02/.72` as exact owners although they are intentionally cold aggregate market entries in current state | Tests encoded a superseded representation and missed the cold materialization lifecycle | Current live obligations are derived from authority; regional fixture now explicitly materializes from aggregate, receives a field contract, tacticalizes, retires, and re-aggregates | Shinobi representation/conservation patterns compared | 45 mercenary/prisoner/second-order tests pass |
| P2 | Sword | MCP hot context | Stable narration/knowledge/choice doctrine was repeated in `narration_guidance` even though the installed Skill already owns it | Repeated bytes and a second static doctrine location that could drift | Compact MCP handoff now retains only runtime-varying stale-scene and campaign-entry flags | Shinobi compact handoff measured for comparison | Production compact packet 48,483 -> 47,506 bytes; 27 context/scene/planning tests pass |

No P0 was confirmed. No test assertion was weakened by changing a mechanical invariant. Stale tests were changed to assert the intended authority relationship instead of historical cardinality or historical object materialization.

## F. Missing-feature / improvement roadmap

Priority is gameplay value and architectural leverage, not maximum feature count.

1. **Integrate Shinobi combat-span safety into the generic combat resolver.** The current production wrapper is functioning, but it is a campaign-specific composition pattern. Move the bounded standing-span and deterministic target policy into a generic registered combat policy so production startup has no one-player patch layer.
2. **Add a progressive contract-list read to Shinobi before contract volume grows further.** Current compact context exposes all 14 visible offers and remains small enough, but contract discovery alone is 7,218 bytes. Introduce a player-safe paged contract listing only if omitted offers remain rediscoverable. Do not truncate first and make mechanics unreachable.
3. **Keep reducing Sword operation context through exact operation reads, not blindness.** The main current hot producer is the active campaign operation. Preserve decision-bearing order/authority/strength summaries; demand-load detailed route/staff planning when a decision actually needs it.
4. **Deepen first-class life pressure where domain appropriate.** Shinobi has rich injury/family/relationship systems but a comparatively sparse illness/disease footprint. Sword has broad life/political systems but desertion appears less developed than prisoners/wounded/logistics. These are roadmap candidates, not confirmed broken mechanics.
5. **Continue causal delivery audits.** Both games have autonomous world work. Keep testing the full chain: autonomous action -> committed state -> information/report/opportunity -> lawful delivery -> playable scene.
6. **Keep representation scale domain-specific.** Do not copy Sword's cohort-first military model wholesale into Shinobi, and do not materialize every Sword soldier as an exact person. Port conservation and materialization principles, not data models.

## G. Context-bloat report

### Sword & Banners measured production composite

Read-only measurement used `ReconnaissanceAwareOperations` and the actual compact MCP handoff on a disposable Git-backed copy.

- Full internal `play_context`: **189,918 bytes**
- Compact MCP context before repair: **48,483 bytes**
- Compact MCP context after repair: **47,506 bytes**
- Repeated narration-guidance component: **1,269 -> 292 bytes**

Largest post-compaction producers remain approximately:

| Component | Bytes |
|---|---:|
| `gm_scene_context` | 11,829 |
| `controlled_operations` | 10,382 |
| `controlled_command_groups` | 2,948 |
| `controlled_formations` | 2,526 |
| `known_information` | 2,380 |
| `interaction_handles` | 2,199 |
| `scene` | 2,177 |
| `player` | 2,173 |
| `commands` | 1,873 |
| `permitted_object_refs` | 1,488 |
| `environment` | 1,441 |

The command surface is not the bloat problem. It is already a compact family catalog. The primary cost is current campaign-command/operation detail, which is legitimate but should remain under continuous budget pressure.

Recommended normal Sword target: **< 48 KB current hot context**, ideally 35 to 45 KB when no major campaign operation is active. Do not achieve this by hiding decision-bearing order/authority facts.

### Shinobi measured production-style composite

Read-only measurement used the actual operations and compact MCP handoff on a disposable Git-backed copy.

- Full internal `play_context`: **20,496 bytes**
- Compact MCP context: **24,985 bytes**

The compact form is larger because it deliberately adds the writer-focused `gm_scene_context`, scene header, presentation contract, and semantic-action contract. It is still materially smaller than Sword and comfortably bounded.

Largest producers:

| Component | Bytes |
|---|---:|
| `contract_reads` | 7,218 |
| `gm_scene_context` | 4,125 |
| `recent_interaction_attempts` | 2,674 |
| `recent_scene_history` | 2,665 |
| `player` | 1,998 |
| `commands` | 1,670 |

Current contract volume is the obvious future scaling pressure. Do not truncate it until a bounded paged discovery path exists, because undiscoverable mechanics are functionally broken.

Recommended normal Shinobi target: **20 to 30 KB**, with a future contract paging path if visible offers grow materially.

Receipts/WAL are correctly absent from ordinary narrative context in both games.

## H. Determinism report

Targeted runtime scans found no direct mechanically significant uses of `random.*`, `uuid4()`, `datetime.now()`, or similar wall-clock/random APIs in the game mechanics layers.

The observed nondeterministic infrastructure paths are intentional and non-mechanical:

- Both games use `time.time()` in `api/mcp_security.py` for preview-attestation/security TTLs.
- Both use `secrets` for authentication token generation/comparison.

These must not influence campaign outcome selection, combat rolls, chronology, or persistent identities. The inspected paths do not use them that way.

The deterministic conclusion is scoped: this was a source scan plus maintained focused tests, not a proof over every Python dependency or a full deterministic replay suite. The long-horizon/replay suites were intentionally not run merely to inflate test count.

## I. Persistence / recovery report

Both repositories use the intended write model:

```text
natural-language intent
-> exact semantic command
-> expected revision
-> preview / attestation
-> execute
-> reducer / staged writes
-> validation
-> commit
-> durability
-> receipt
-> refreshed context
-> narration
```

The maintained tests exercised stale-revision/transaction behavior, recovery hardening, branch bootstrap, deployment attestation, and crash-recovery paths. Exact duplicate/retry behavior remains receipt/idempotency owned rather than LLM-owned.

Important deployment boundary:

- Source checkout, Git campaign durability, private WAL/receipts, Railway deployment, MCP schema refresh, installed Skill, and chat context are separate delivery tiers.
- The packaged ZIPs intentionally do not contain a live private recovery store.
- A fresh recovery store must not be expected to prove a historical one-off WAL chain. This is why the Shinobi rev143 anchor is no longer production-installed.

No campaign-truth files were advanced or rewritten as part of the audit repairs.

## J. World-simulation report

### Sword

Current `state/runtime.json` reports:

- 403 hosts
- 403 events
- scheduler `dirty=false`
- last coverage `complete=true`
- zero recorded coverage errors and zero overdue host refs in the current coverage snapshot
- causal settlement through the current campaign time

Focused scheduler/event/living-world tests passed. The architecture has explicit report/opportunity/event delivery and player-safe handoff layers, so autonomous work is not designed as invisible state churn.

### Shinobi

Current scheduler state is settled through the current campaign time and contains 4 recurring plus 45 one-off jobs. The audit ran 99 focused scheduler/economy/social/escort living-world tests. It also passed state ownership and no-op round-trip checks. Current design routes world work through causal owners and player-facing contracts/missions/events rather than expecting the LLM to remember every job.

The remaining cross-game requirement is ongoing causal-delivery testing. A background event that never becomes observable, reportable, or interaction-relevant is still a gameplay failure even if mechanically valid.

## K. Narrative-system report

Both games are architecturally aligned with the desired narrative model:

- The runtime is the law of the world, not the story engine.
- Conversation and reversible performance do not require a bespoke Python command.
- Hard consequences do require runtime authority.
- Present NPCs can initiate dialogue/action without a formal conversation session acting as an activation flag.
- Formal sessions preserve continuity but cannot create presence.
- Runtime command success does not end a scene.
- `gm_scene_context` is a writer workspace, not a report template.
- Hidden GM truth can drive lies, hesitation, tactics, and coherent motives without leaking to Wei.
- The Skill, not dynamic runtime payloads, owns stable prose/agency/choice doctrine.

The most likely narrative failure mode now is not lack of doctrine. It is either stale/overlarge context or causal events failing to reach the scene layer. The Sword context repair directly reduces one source of prompt duplication. The Shinobi context remains small enough that further compression should be retrieval-led rather than indiscriminate.

## L. Revision / rebaseline decision

**Rebaseline approved and performed after the audit at the player's direction.**

Both packages now use explicit revision-1 baselines. The repaired current hard-world snapshot is preserved as canonical starting truth, while old revision lineage is forensic evidence only. Authority-false scene/session/dialogue residue from development play was cleared, and the old complete `state/` snapshot is archived under `docs/forensics/`. No prior WAL or idempotency receipt is carried into the baseline.

This is not an in-place rewind. Production deployment must use a fresh persistent campaign checkout and fresh private WAL/receipt store. The existing fail-closed future-receipt and higher-local-revision guards remain intact. See `docs/CAMPAIGN_REBASELINE_20260902.md`.

## M. Actual code repairs delivered

### Shinobi

1. `runtime/shinobi_runtime/api/campaign_entrypoint.py`
   - Removed production installation of the rev143 historical repair anchor.
   - Clarified that one-off historical repair anchors are excluded from current live composition.
2. `runtime/shinobi_runtime/api/historical_repair_anchor.py`
   - Reframed the helper as forensic/replay-only after the repaired baseline became canonical.
3. `tests/current/test_pre_root_historical_repair.py`
   - Regression now requires the production entrypoint to exclude the legacy anchor while the generic repair API remains clean.

### Sword & Banners

1. `tests/runtime/test_second_order_audit_repairs.py`
   - Replaced stale hard-coded live-contract count with the real invariant: live mercenary obligations exactly equal routed mercenary scheduler hosts; cold accounting companies have none.
2. `tools/test_changed.py`
   - Added mercenary and prisoner owner-to-regression routing.
3. `tests/runtime/test_mercenary_tacticalization.py`
   - Removed historical exact-owner assumptions.
   - Current Qin field obligations are derived from authoritative owners.
   - Regional regression now proves aggregate -> exact materialization -> tactical formation -> contract completion -> tactical retirement -> aggregate market conservation.
4. `runtime/sword_runtime/api/command_discovery.py`
   - Removed stable Skill doctrine from repeated MCP narration guidance.
   - Preserved dynamic stale-scene and campaign-entry authority flags.
5. `tests/runtime/test_stable_operations.py`
   - Added regression proving static narration doctrine is not repeated in the compact MCP payload.

## N. Verification ledger

### Shinobi

| Check | Why it was run | Result |
|---|---|---|
| `python tools/quick_check.py` | Structural/package/schema/ownership gate after edits | PASS |
| `python tools/test_changed.py ...campaign_entrypoint...historical_repair...` | Maintained changed-owner regression gate | PASS, 80 tests |
| Focused pre-root/release/branch/crash-recovery batch | Verify historical repair retirement did not damage generic recovery/startup | PASS, 52 tests |
| `test_continued_audit_repairs.py` | Existing cross-system audit regression | PASS, 72 tests |
| `test_post_audit_repairs.py` | Existing post-audit regression | PASS, 6 tests |
| `test_post_context_repairs.py` | Context/retrieval regression | PASS, 9 tests |
| `test_open_world_gm_architecture.py` | LLM/runtime/scene separation | PASS, 17 tests |
| `test_transaction_crash_recovery.py` | Failure/recovery semantics | PASS, 4 tests |
| `test_physical_presence_authority.py` | Canonical co-presence authority | PASS, 4 tests |
| `python tools/audit_state_bloat.py` | State/context scaling diagnostic | PASS |
| `PYTHONPATH=runtime python tools/verify_noop_roundtrip.py` | No-op deterministic state round trip | PASS |
| Scheduler/economy/social/escort living-world batch | Autonomous causality and delivery | PASS, 99 tests |
| Production-style context measurement on disposable Git copy | Measure actual hot packet | Full 20,496 B; compact 24,985 B |

### Sword & Banners

| Check | Why it was run | Result |
|---|---|---|
| `python tools/quick_check.py` | Syntax/JSON/registered-schema gate after edits | PASS, 1,374 JSON files / 235 schemas |
| `test_second_order_audit_repairs.py` | Confirm stale count repair | PASS, 10 tests |
| Mercenary + policy + prisoner + second-order batch | Validate contract routing, conservation, tacticalization, cold aggregation, custody | PASS, 45 tests |
| Stable/context/planning/open-world batch | Verify context compaction and scene/GM contract | PASS, 27 tests |
| Architecture + transaction core batch | Exact command/transaction invariants | PASS, 22 tests |
| Household + interaction batch | Scene/social access and continuity | PASS, 13 tests |
| Recovery hardening + branch bootstrap + deployment attestation | Failure/restart/deployment boundaries | PASS, 21 tests |
| Scheduler frontier + event liveness + production living world | Autonomous causal progression | PASS, 18 tests |
| `test_open_world_gm_architecture.py` earlier focused run | LLM/runtime separation | PASS, 16 tests |
| Production composite context measurement | Quantify actual MCP bloat | 189,918 B full; 48,483 B compact before; 47,506 B after |
| Aggregate `python tools/test_changed.py ...` | Maintained route selection | TIMED OUT after progressing through selected tests; not reported as pass/fail. Every module it selected was then run in smaller batches above and passed. |

The audit intentionally did not repeatedly run the expensive full release or long-horizon 50-year simulation suites.

## O. Remaining risks and non-claims

1. **No live Railway deployment was performed from these ZIPs.** Local source correctness is not proof of Railway source-head sync, environment variables, remote Git durability, MCP connector refresh, or installed Skill refresh.
2. **Hosted GitHub CI was not verified in this local ZIP audit.** The packages are ready for the repository's normal PR/CI/deploy pipeline, but local green is not CI green.
3. **Full release/replay/soak suites were not run.** This is deliberate. Long-horizon verification should be run when preparing an actual release or when changes touch the relevant deterministic/recovery subsystem.
4. **Shinobi's production combat-span safety wrapper remains technical debt.** It works and is covered, but the generic combat resolver is the better eventual home for that policy.
5. **Sword's 47.5 KB compact handoff is acceptable but still near its current budget.** The active campaign operation is the next logical progressive-loading target if it grows.
6. **Shinobi contract discovery is the largest hot-context producer.** Do not simply truncate it. Add paged/player-safe discovery first if contract volume grows.
7. **Static nondeterminism scans are not a formal whole-program determinism proof.** They found only security/auth wall-clock randomness in the inspected runtime tree.
8. **The package was subsequently rebaselined to revision 1 without advancing world time.** The prior snapshot remains forensic-only under `docs/forensics/`; deployment requires a fresh private recovery store.

## Final architectural conclusion

The games are not fighting the LLM at the architectural level. Their strongest shared design is already the correct one: deterministic runtime truth plus bounded semantic access, with the LLM retaining scene direction and human performance. The repairs in this package reinforce that line instead of adding more command-shaped storytelling.

The next gains should come from progressive retrieval, continued causal-delivery testing, genericizing remaining campaign-specific production wrappers, and deeper release/replay verification at actual release time, not from moving dialogue, pacing, or NPC moment-to-moment behavior into deterministic code.

## P. Post-audit narrative and rebaseline hardening

After the original audit, the player explicitly raised the narrative bar and approved a clean revision baseline. The packages were therefore hardened further:

1. Added a universal **serialized saga** contract to the repository Skill. It applies to every scene, including personal combat and large warfare, and explicitly requires buildup, evolving pressure, reversals, consequence, and aftermath without authorizing invented mechanics.
2. Expanded narration, scene-craft, and combat/warfare references so major scenes can develop across turns instead of collapsing into one response-sized summary.
3. Made cross-game analogous-defect review mandatory for confirmed P0/P1/systemic P2 defects before global closure.
4. Wired those narrative and cross-game contracts into each repository's `tools/test_changed.py` so future Skill edits automatically exercise them.
5. Created a revision-1 baseline while preserving the repaired hard-world snapshot. Old complete state is retained under `docs/forensics/` for failure analysis; development-era scene/session/dialogue residue is not active authority.
6. Kept fail-closed deployment semantics. The revision-1 package must start with a fresh persistent campaign checkout and private WAL/receipt store.

### Additional verification

- Final structural `quick_check.py`: PASS.
- Skill/rebaseline changed-path selector: PASS, 44 passed in 12.43s.
- Focused architecture/rebaseline/scene/history/transaction batch: PASS, 86 tests.
- Fresh-snapshot/rebaseline integration batch: PASS, 26 tests.
- Campaign event liveness: PASS, 1 test. World arcs: PASS, 22 tests. Production living-world: PASS, 7 tests. Living-world intelligence excluding the deliberate 120-day replay: PASS, 7 passed / 1 skipped / 1 deselected.
- The aggregate changed-path invocation that included the 120-day replay exceeded the execution window; it is recorded as timed out, not as pass/fail. The long replay was not required for these Skill/rebaseline edits and was not rerun to inflate the ledger.

