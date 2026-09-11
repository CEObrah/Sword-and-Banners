# Sword & Banners Full-System Root-Cause Audit

Date: 2026-09-07

Editing authority: local `Sword-and-Banners-main-PR194-merged.zip` package derived from PR #194 branch head `37b7606ca557396556b33d541fe8c29ef6a9bf3d`.

Campaign snapshot audited: `sword-banner-tang-wei-main`, revision 45, world time `244-BCE-12-21T12:00:01+08:00`.

## Executive conclusion

The repeating gameplay failures were not a collection of unrelated bugs. The audit found a small set of architectural contradictions that allowed different runtime layers, old compatibility paths, tests, and validators to implement different definitions of the same campaign truth.

The dominant root causes were:

1. **Current identity was sometimes inferred from collection order instead of an explicit authoritative reference.**
2. **Decision issuance, physical receipt, staff actionability, and completion were sometimes collapsed into one lifecycle stage.**
3. **Some writers truncated history even though other fields stored explicit references into that history.**
4. **Legacy aggregate military cohorts lacked newer local-provenance fields, allowing global casualty conservation to succeed while local service partitions silently retained dead bodies.**
5. **Tests and release validators preserved older repository architecture and campaign-layout assumptions after production semantics had moved on.**
6. **Hot autonomous code repeatedly re-read stable routing/index documents, creating excessive logical read fanout even though exact owner bytes were already cached.**
7. **Future-state archive metadata could be emitted by the runtime without being admitted by the registered owner schema, so current-state validation stayed green until a long campaign first crossed the archive threshold.**
8. **Hot-state compaction and registered schemas could contradict each other, allowing a future owner serialization to require explanatory fields that the compactor deterministically strips.**
9. **The changed-path test router ran all selected integration modules in one pytest process, retaining disposable Git-backed campaign clones until final teardown and eventually exhausting filesystem inodes during systemic audits.**

The highest-value correction is therefore not another campaign-specific exception. It is the explicit invariant that **identity, lifecycle stage, ownership, and history are separate concepts** and must remain separate throughout write, persistence, projection, causal settlement, and narration.

## 1. Intended architecture

The intended authoritative path is:

```text
player natural-language intent
  -> fresh bounded play context
  -> exact owner reads only when material
  -> reversible scene realization
  -> hard-consequence classification
  -> exact mechanic family / command contract
  -> read-only preview
  -> exact attested execute
  -> staged transaction
  -> invariant/schema validation
  -> WAL + Git durability + immutable receipt
  -> revision increment
  -> exact authoritative owners
  -> derived authority:false indexes/projections
  -> causal scheduler settlement
  -> information/report/order delivery
  -> fresh play context
  -> GM scene direction and lived narration
  -> next genuine player decision
```

The architecture already correctly separates `game/` static authority, `runtime/` executable behavior, and `state/` mutable campaign truth. `authority:false` indexes and projections are routing/presentation aids only.

The military representation chain is intended to remain conserved:

```text
population -> force/cohort -> persistent formation -> temporary operation/battle arrangement
```

An operation's `operational_orders` is durable historical evidence. `last_operational_order_ref` is the explicit current-order identity. Collection position is not authority.

A superior campaign decision has a lifecycle rather than a single boolean state:

```text
issued -> routed in physical transport -> received -> staff-actionable/current -> completed/superseded
```

The prior executable mission remains current until the new order crosses the lawful delivery/actionability boundary.

## 2. How the implementation diverged

### 2.1 Multiple private definitions of “current order”

Several runtime modules had private `_latest_order()` behavior. Some used `last_operational_order_ref`, while compatibility paths could fall back to the array tail. The API/projection side was stricter.

The revision-45 save proves those concepts are not interchangeable. Tang Wei's operation can contain a newer `issued_pending_delivery` order at the history tail while `last_operational_order_ref` correctly points to the older delivered/executable mission.

Therefore:

```text
latest historical record != current executable order
```

Any reader that substitutes the tail can make the simulation act on a different mission than the player-facing context reports.

### 2.2 Legacy reconciliation contradicted delivery causality

The campaign-order guard correctly preserves the prior executable mission while a new superior directive is still in transit. A legacy Qin command-support reconciliation path could later re-promote a newer order according to issuance chronology.

That made two adjacent systems encode opposite rules:

- order guard: receipt/actionability establishes current identity;
- reconciliation: newer issuance can establish current identity.

This explains why the same bug could appear “fixed” and then return after an ordinary time-advance/reconciliation cycle.

### 2.3 Durable-reference fields pointed into bounded/truncated history

Some operational-order writers retained only `orders[-16:]` or `orders[-32:]` while the operation stored explicit references to historical orders. In a long campaign, the writer could eventually discard the row required by the explicit pointer.

That is a revision-5,000 failure mode even if revision 45 still resolves correctly.

### 2.4 Semantic equivalence was used as record identity

Autonomous Qin retasking could derive `order_ref` from semantic content alone. Reissuing the same lawful directive after an older identical order completed could therefore recreate the same identity.

The correct distinction is:

```text
semantic_key = what kind of order this means
order_ref = this exact issuance event
```

A retry of the same causal action should be deterministic. A later reissue of the same semantics must receive a new occurrence identity.

### 2.5 Legacy casualty provenance broke only the local partition

Autonomous battle casualties were globally conserved correctly. However, local-origin reconciliation skipped old baseline cohorts that predated `origin.population_ref` / source-location provenance.

This produced a subtle split-brain conservation state:

- global state population: soldier is dead;
- local `serving_native_military` partition: same soldier still counted alive/in service.

The exact accumulated discrepancies were:

- Wei: 3,818
- Han: 1,261

Those values match the autonomous battle casualty ledgers exactly, establishing the causal source rather than merely balancing totals.

### 2.6 Release tooling encoded retired architecture

The current merged package initially failed its own release validator for checks that no longer represented production architecture, including:

- expecting retired `verify.yml` rather than current `runtime-tests.yml`;
- treating fortification index routes as inline owner objects;
- requiring a named exact commander for every large formation despite aggregate/vacant command representations;
- requiring `officer_cadre` for an aggregate mercenary command representation;
- rejecting lawful future one-shot host `resolved_through` initialization.

Once those validator assumptions were corrected, the genuine Wei/Han local casualty drift became visible.

This demonstrates why a red validator is not automatically proof of broken campaign truth and a green validator is not proof that the validator still tests the current architecture.

### 2.7 Future archive writes escaped current-state schema parity

The causal event store correctly spills old triggered events into exact archive segments after the hot head exceeds its limit. That write path also persists cumulative archive metadata such as `archive_segment_count` and `archived_kind_counts`. The registered `event-registry` schema did not admit those fields.

Current-state validation could therefore remain green for months of real play while the first sufficiently mature future transaction failed closed during staged schema validation. A 120-day disposable replay reproduced the failure. The schema now admits the runtime-owned bounded archive metadata, and the direct overflow regression validates the staged hot owner against the registered schema immediately after compaction.

This is a separate form of verification drift: validating only the present snapshot is insufficient when important owners have deterministic future-state transitions such as archival, compaction, rollover, or migration.

### 2.8 Hot-state compaction contradicted a future military-career schema

The generic hot-state compactor recursively removes explanatory/provenance keys such as `rule`, `note`, and `notes` before mutable owners are persisted. The military-career petition schema simultaneously required `personnel_action_handoff.rule`. Those contracts are mutually impossible: once a future petition reaches the `authorized_handoff` shape and is compacted, staged schema validation must fail closed.

A 120-day disposable replay exposed this only after the earlier causal-event archive blocker was removed. The untouched merged ZIP never reached this later failure because it first failed on the archive-schema defect. The durable handoff contract now stores only mechanical authority/action fields; explanatory `rule` prose remains non-authoritative and is not required by the schema. A generic architecture regression scans every schema referenced by current `state/` **and every registered root owner schema**, rejecting any `required` field that belongs to the hot compactor's explanation-key set. This covers mutable owner types that have not materialized in revision 45 yet while excluding static mechanics registries that never pass through hot-state compaction.

This is broader than military careers. It establishes that compaction policy and formal schema policy are one serialization contract and must be verified together.

### 2.9 Changed-path certification accumulated disposable fixture trees

`tools/test_changed.py` previously passed every selected regression module to one pytest process. That is acceptable for a tiny slice, but a root-level audit can select dozens of integration modules, many of which clone the full campaign repository. Pytest retained those basetemps until the monolithic session ended. During this audit the container reached **100% inode usage with zero free inodes**, after which unrelated fixtures began reporting a contiguous cluster of setup `E` errors.

Those errors were environmental artifacts, but the harness design made them likely and therefore made certification itself unreliable. The router now runs each selected module in its own fresh process, assigns a run-scoped disposable `--basetemp`, and removes that basetemp immediately after the module exits. This also yields a real per-module exit boundary instead of one giant teardown.

The correctness standard is unchanged: every selected maintained module must still pass. The fix changes only isolation and cleanup, not which tests are selected or what they assert.

### 2.10 Long-horizon performance guard encoded an old campaign snapshot

The old hosted-horizon test documented a 365-day reference of 2,739 events and imposed an 8-events/day slope. The untouched revision-45 merged package actually settles approximately:

- 30 days: 280 events
- 90 days: 825 events
- 365 days: 3,418 events

The density remains roughly linear at about 9.2 to 9.4 events/day. This is historical fixture drift, not a causal event explosion.

The release harness also gave the 90-day node only 90 seconds even though the untouched package takes roughly two minutes in this execution environment. The correctness/complexity assertions remain intact; only the finite harness budget was corrected.

Separately, profiling found real logical-read fanout from repeated owner/index routing reads. Planner-local routing caches were added for stable routing documents with write/delete invalidation. Exact owner documents remain authority.

### 2.11 Military-logistics growth fixture inherited insufficient live treasury

The changed-path router later reached a state-force authorization regression that expected Qin to expand regular-force authorization by at least 500 personnel under an injected severity-85 frontier threat. The untouched merged ZIP failed the same test. The current revision-45 Qin treasury is below the force-posture rule's configured two-month reserve floor after ordinary monthly expenses, so the runtime correctly returned `material_growth_capacity_below_granularity` with `affordable: 0`.

The runtime invariant was correct; the fixture's material-capacity premise was not. The regression now funds its treasury premise from the registered reserve-month and basic-issue-cost rules before invoking the integrated autonomy path. It still exercises the real authorization -> conserved civilian recruitment -> active-military transfer and would still fail if the runtime bypassed reserve, population, office-capacity, or recruitment conservation constraints. This is another example of why mutable live campaign balances cannot serve as implicit test setup.

## 3. Revision-pattern timeline

The repository history shows repeated repairs clustered around one campaign seam rather than random failures.

Representative history:

- PR #171 / #172: Sanyou phase, zero-distance arrival, satisfied-arrival reconciliation.
- PR #185: unified follow-on response admission and physical routing.
- PR #186: separated superior decision issuance from physical order delivery.
- PR #187: vitality detection for campaign orders exposed before delivery.
- revision 35 gameplay reconciliation: `ooc-dev-qin-command-support-reconcile-r34`.
- revision 37 gameplay reconciliation: `oocdev-reconcile-qin-r36`.
- revisions 38-45: repeated route/recovery/follow-on/order-delivery reconciliation transactions.
- PR #191: CI/baseline repair.
- PR #193: revision-45 campaign-state synchronization.
- PR #194: exact treaty/order selection regressions and causal-event archive discovery fix.

The repetition is diagnostic. Arrival, request, response, order, delivery, current mission, and follow-on behavior were being repaired at neighboring surfaces while their shared lifecycle/identity abstraction remained inconsistent.

## 4. Symptom atlas

| Surface symptom | Common underlying category |
|---|---|
| Wrong treaty/order chosen | identity inferred from collection order |
| New order appears executable before courier arrival | issuance/receipt/actionability conflation |
| Time advance “undoes” a prior order fix | legacy reconciliation owns a second current-order rule |
| Movement scope follows pending directive instead of current mission | consumer bypasses explicit current-order authority |
| Reissued equivalent order collides with historical record | semantic equivalence confused with occurrence identity |
| Long campaign may lose referenced order | bounded history contradicts explicit refs |
| Correct global casualties but impossible local populations | provenance gap across conservation partitions |
| Release gate reports old workflow/index/command errors | verification architecture drift |
| Long-horizon guard fails despite linear causal work | snapshot-specific performance expectations |
| First event archive spill fails schema validation | future-state runtime/schema parity gap hidden by current-snapshot validation |
| Future military-career handoff fails only after compaction | hot-state compactor/schema contract contradiction |
| Broad changed-path suite suddenly emits many setup `E` errors | monolithic test basetemps exhausted filesystem inodes |
| Correct world event exists but cannot be surfaced | existence/discoverability or delivery-routing split, including the PR #194 archive-segment defect |

## 5. Persona findings

### Runtime architect

The core stack is sound, but campaign order identity was not represented through one reusable authority boundary. The fix centralizes current identity and keeps projections/readers subordinate to exact owner state.

### Persistence/revision engineer

Campaign revision, source Git revision, delivery chronology, and order identity are distinct. Historical fixes sometimes reasoned from convenient list layout rather than durable identity. No campaign revision rewind is warranted.

### Causal/scheduler engineer

The scheduler frontier is healthy after reconciliation. `last_coverage` is historical diagnostic metadata, not current host authority. Delivery hosts and one-shot cursor semantics needed validator alignment. PR #194's causal-event archive fix is consistent with the broader rule that durable existence and ordinary discoverability are both required.

### State/conservation auditor

The major real campaign-truth defect was the local military population partition. Global deaths were already correct. The repair therefore changes only local service partitions and leaves global population, force strength, battle results, time, and revision unchanged.

### API/projection engineer

The API is strongest when it fails closed on missing explicit current identity. Production consequence readers must use the same definition. Bounded windows and authority:false indexes remain routing only.

### Mechanics designer

No evidence from this audit required changing combat, morale, siege, or battle-resolution rules. The important mechanics defect was composition across casualty owners and local population provenance, not the casualty numbers themselves.

### GM/scene/narrative director

The current Skill architecture already contains the required novel-first scene rules: command completion is not scene completion, NPCs may initiate on `continue`, first lived beat should be concrete, and narration must not collapse into state reports. A failing fiction-rendering test was stale because it expected no routine OOC QA footer, while current Skill/project authority explicitly requires one compact `OOC QA:` line after live turns. The test was corrected rather than weakening the current presentation contract.

### Test/regression engineer

Several tests were asserting layout rather than invariants, especially `operational_orders[-1]` and old campaign snapshot constants. Regressions now use explicit current refs, misleading-tail fixtures, duplicate-ID fixtures, long-history fixtures, exact delivery lifecycle states, archive after-image validation, and a generic schema/compactor compatibility scan for all schemas referenced by current state.

### Red-team engineer

The most dangerous adversarial cases were harmless history reordering, multiple historical orders, a pending tail after an executable current order, equivalent reissuance, missing legacy provenance, archive boundaries, and long-history growth. Those cases now have direct guards or are called out as remaining migration limitations.

### Synthesis chair

The repeated bugs collapse into a few root clusters: identity/order conflation; lifecycle-stage conflation; history/reference contradiction; conservation provenance gaps; serialization-contract drift; verification drift; routing-layer performance overhead; and certification-harness resource accumulation.

## 6. Root-cause matrix

### RC-01: Current identity inferred from order

- Severity: P1
- Confidence: High
- Symptom: wrong order/treaty/movement scope selected after history accumulates
- Player impact: simulation and narration can disagree about the active mission
- Authority: exact operation owner + `last_operational_order_ref`
- Root mechanism: private readers inferred current identity from history position
- Why earlier fixes recurred: tests/consumers were repaired individually while sibling readers kept older semantics
- Root fix: centralized explicit current-order authority; no tail fallback
- Regression: misleading pending tail, history reordering, missing pointer, duplicate pointer identity, long history
- Shinobi analogue: no equivalent operational-order history model found

### RC-02: Issuance, delivery, and actionability conflated

- Severity: P1
- Confidence: High
- Symptom: new strategic directive becomes active before physical receipt/staff packet
- Player impact: impossible knowledge/authority and premature movement
- Authority: campaign decision + delivery route + operation current pointer
- Root mechanism: decision writer/reconciler could promote at issuance rather than lawful receipt boundary
- Why earlier fixes recurred: delivery guard and reconciliation encoded opposite semantics
- Root fix: pending orders append as historical issued-pending-delivery records; current pointer changes only at lawful delivery/actionability boundary; reconciliation repairs routes only
- Regression: pending newer tail must not displace prior current executable order
- Shinobi analogue: no direct equivalent campaign-order transport model found

### RC-03: Explicit refs into truncated history

- Severity: P1 long-horizon
- Confidence: High
- Symptom: current/ref-linked order can disappear after enough writes
- Player impact: campaign can fail only after long play, making bug difficult to reproduce early
- Authority: operation order history
- Root mechanism: writers retained last 16/32 rows while explicit fields referenced historical identities
- Root fix: lossless append for operational-order history
- Regression: append beyond old truncation horizon and still resolve current ref

### RC-04: Semantic key reused as occurrence ID

- Severity: P1
- Confidence: High
- Symptom: legitimate reissue collides with completed historical order
- Player impact: duplicate identity, failed routing, or accidental deduplication
- Authority: exact operation order record
- Root mechanism: `order_ref` derived only from semantic content
- Root fix: preserve semantic key but derive occurrence identity from semantic key + causal action ref
- Regression: same semantics under new action yields new ID; same retry remains deterministic

### RC-05: Legacy casualty provenance gap

- Severity: P1 campaign truth
- Confidence: High
- Symptom: state-local military populations exceed global active military after autonomous battles
- Player impact: phantom manpower and eventual recruitment/economic/logistics distortion
- Authority: state population + force cohort provenance + battle casualty evidence
- Root mechanism: local reconciliation skipped legacy cohorts without newer origin fields
- Root fix: exact provenance when available; deterministic native local allocation fallback only for legacy same-state cohorts; fail closed when conservation cannot be proven
- Campaign repair: Wei -3,818 local service; Han -1,261 local service; global totals unchanged
- Shinobi analogue: no direct equivalent; Shinobi martial manpower is exact-person-derived

### RC-06: Verification architecture drift

- Severity: P2 systemic
- Confidence: High
- Symptom: release validator fails valid new architecture or tests preserve old save layout
- Player impact: repeated pressure to patch correct runtime toward obsolete expectations, and real defects can hide behind noisy failures
- Root fix: align validator/test assertions to current invariants; make release suite invoke structural/conservation validator; make material-capacity tests explicitly establish the treasury/food/population premises they claim rather than inheriting mutable live balances

### RC-07: Repeated routing-index logical reads

- Severity: P2 systemic/performance
- Confidence: High
- Symptom: long-horizon read fanout grows far faster than the actual causal event count
- Player impact: slower verification and eventually slower autonomous chronology
- Authority: none; indexes are non-authoritative routing
- Root mechanism: hot paths repeatedly enter the same owner/operation/command-group/location routing docs in one planner transaction
- Root fix: planner-scoped routing-document caches with immediate invalidation on staged mutation; exact owner documents remain uncached authority reads through normal planner cache semantics
- Regression: staged owner-index/routing-document write must invalidate cache and be observed immediately

### RC-08: Future causal-event archive metadata missing from registered schema

- Severity: P1 long-horizon persistence
- Confidence: High
- Symptom: mature disposable replay fails when the causal-event hot head first archives enough records
- Player impact: a long-lived campaign can become unable to commit otherwise lawful chronology once archive compaction emits metadata rejected by formal validation
- Authority: causal event owner + registered `event-registry` schema
- Root mechanism: runtime writer and schema evolved independently; current-state fast gates never exercised the future archive after-image
- Why earlier checks missed it: revision-45 current state had not yet staged the exact failing metadata combination during ordinary validation
- Root fix: register `archive_segment_count` and `archived_kind_counts`, bound archive metadata length, and validate the post-overflow owner directly in the causal archive regression
- Regression: force hot-head overflow, validate the staged owner against the registered schema, then rehydrate an archived exact ref
- Shinobi analogue: its event/persistence design is independent; no shared causal-event archive owner/schema was found

### RC-09: Hot-state compactor and schema required-field contradiction

- Severity: P1 long-horizon persistence
- Confidence: High
- Symptom: a mature replay fails when a future military-career petition reaches `personnel_action_handoff` and the compacted owner no longer contains schema-required `rule` prose
- Player impact: otherwise lawful future chronology can become uncommittable only after enough campaign development creates the affected owner shape
- Authority: hot-state serialization contract + registered owner schema
- Root mechanism: the generic compactor recursively strips explanatory keys while one state-used schema independently required one of those stripped keys
- Why earlier checks missed it: current revision-45 owners had not yet materialized the failing petition shape, and the untouched package hit the causal-event archive schema defect first
- Root fix: remove explanatory `rule` from the durable required handoff contract and enforce a repository-wide regression that no current-state schema or registered mutable-owner schema requires any hot-compactor explanation key
- Regression: compact a representative personnel handoff and validate it against the registered petition schema; separately scan all current-state schemas plus all registered root owner schemas for forbidden required keys
- Shinobi analogue: independent serialization/schema system; no shared Sword schema dependency exists

### RC-10: Monolithic changed-path router exhausted filesystem inodes

- Severity: P2 systemic QA architecture
- Confidence: High
- Symptom: a broad `test_changed.py` run changes from normal pass markers to a contiguous cluster of setup errors after enough integration fixtures accumulate
- Player impact: false-negative certification, wasted repair cycles, and pressure to change correct runtime code in response to infrastructure failure
- Authority: test harness only; no campaign/gameplay authority
- Root mechanism: all selected modules shared one pytest process and default basetemp lifetime, so Git-backed disposable campaign clones survived until final teardown
- Evidence: audit environment reached 100% inode use with 0 free inodes; killing the invalid run and removing disposable pytest/replay trees restored inode use to about 2%
- Root fix: run each selected module in a fresh process with a run-scoped `--basetemp`, delete each basetemp immediately after that module exits, and clean the run root on normal completion
- Regression: harness-policy test requires per-module iteration, explicit isolated basetemp, immediate cleanup, and forbids the old one-process `*tests` invocation
- Gameplay/state impact: none

## 7. Explicit invariants established by this audit

1. **Current identity is explicit.** Historical collection position never establishes current mission identity.
2. **History ordering is evidence, not authority.** Reordering non-semantic collections must not change current truth.
3. **One occurrence, one identity.** Equivalent semantics may share a semantic key but not an issuance ID.
4. **Order issuance is not player receipt.** Physical/institutional delivery gates actionability where the domain requires it.
5. **Reconciliation repairs routing, not authority.** A compatibility/recovery path cannot manufacture a new current order by chronology.
6. **Explicit references require durable referents.** Writers cannot silently truncate identity-bearing history that live refs may still name.
7. **One durable fact, one owner.** Indexes and projections never become alternative campaign truth.
8. **Population conservation spans all partitions.** Global and local ledgers must reconcile after casualties/recruitment/migration/materialization.
9. **Legacy fallback requires proof.** Missing provenance may use only deterministic, ownership-proven aggregate reconciliation; otherwise fail closed.
10. **A bounded page is not the world.** Truncation/pagination never means absence.
11. **Durable events must remain discoverable.** Exact-ID existence alone is insufficient for player-facing causal events.
12. **Command completion is not scene completion.** Runtime transaction boundaries do not dictate narrative boundaries.
13. **Tests preserve invariants, not yesterday's save ordering.** Mutable campaign fixtures cannot be treated as pristine snapshots.
14. **Release validators are architecture clients.** They must evolve with owners/indexes/workflows rather than freezing retired representation details.
15. **Performance guards measure causal complexity, not machine speed.** Event/read/write slopes are legitimate release invariants; arbitrary wall-clock assumptions are not.
16. **Routing caches are never authority.** They are planner-local, whole-document, and invalidated on staged writes/deletes.
17. **Future-state owner transitions require schema parity.** Archive/compaction/rollover after-images must be tested against their registered schema before current campaign age happens to reach the threshold.
18. **Compaction and schema form one serialization contract.** A state-used schema may never require a field the hot-state compactor deterministically strips.
19. **Certification resources are bounded per module.** Broad changed-path verification must not retain disposable campaign clones until one monolithic pytest teardown.

## 8. Source changes made

The audit changes include:

- central current-order and append authority in `operation_routing.py`;
- campaign readers routed through explicit current identity;
- issuance/delivery lifecycle separation in campaign decision/support paths;
- removal of chronology-based current-pointer reconciliation;
- lossless operational-order append paths;
- unique occurrence IDs for semantically repeated autonomous orders;
- startup fail-closed checks for missing/unresolved/duplicate/undelivered current order identity;
- vitality detection of pending briefing work independent of current mission identity;
- local-service casualty provenance repair logic;
- validator updates for current workflow/index/command/host semantics;
- release-suite integration of structural/conservation validation;
- long-horizon invariant refresh for revision-45 causal density and finite node budgets;
- planner-local routing/index caches with mutation invalidation;
- event-registry schema parity for causal archive segment/kind-count metadata plus a direct staged-overflow validation regression;
- military-career petition schema/compactor parity plus a repository-wide guard across current-state and not-yet-materialized registered owner schemas against required hot-state explanation keys;
- changed-path test sharding with per-module disposable basetemps and immediate fixture cleanup to prevent inode-exhaustion false failures;
- invariant-focused regressions, including misleading-tail, long-history, reissue, casualty provenance, startup integrity, routing-cache invalidation, archive schema parity, and current narrative OOC-QA contract.

## 9. Campaign-truth repair

A narrow revision-45 campaign repair was justified because already-committed deaths were still represented in local service partitions.

Provenance:

`docs/forensics/repair-provenance/local-service-casualty-partition-20260907.json`

The one-shot revision-45 repair utility was removed after successful application so it cannot be rerun against live state. Its immutable provenance and exact correction evidence remain in the forensic JSON above.

The repair did **not** change:

- campaign revision;
- world time;
- global state population total;
- global active military total;
- battle casualties/outcomes;
- force strength independently of existing casualty authority;
- territory;
- command authority;
- player agency.

Because legacy cohorts did not preserve exact site-of-origin provenance, the precise geographic origin of each already-dead soldier is unknowable. The repair therefore makes only the strongest supported claim: those bodies must be removed from the state's existing native local-service allocations. Their local debits are deterministic aggregate reconciliation, not invented exact historical origins.

## 10. Cross-game analogue audit

`CEObrah/Shinobi-RPG` was inspected independently.

Results:

- no Sword-style `operational_orders` + explicit current-pointer campaign model exists there;
- martial manpower is derived from exact people/current readiness rather than Sword's aggregate force/local-service partition;
- civilian population is derived from place pools;
- the same casualty-provenance defect therefore does not reproduce directly;
- Shinobi's release process already composes structural verification and long-horizon checks more explicitly, which supports the Sword verification consolidation conceptually without introducing any cross-repository runtime dependency.

No Shinobi code patch is required for the defects confirmed here.

## 11. Verification

This section is updated only with checks that actually completed. A timed-out or interrupted command is not counted as passing.

Current completed evidence before final package certification:

- `python tools/quick_check.py`: PASS on the current post-serialization-fix tree (1,652 JSON files parsed; 236 registered schemas validated).
- `python tools/validate_release.py`: 124/124 checks PASS on the current post-serialization-fix tree.
- focused current-order/delivery/startup/casualty/cache suite: 36 passed, 4 expected xfails on the routing-cache tree.
- narrative/scene architecture suite: 93 passed after correcting the stale OOC-QA test.
- cached 30-day hosted horizon: PASS.
- cached 90-day hosted horizon with the strict 150k fixed read allowance: PASS.
- exact 120-day deterministic replay after military-career schema/compactor repair: 1 passed in 286.72s; canonical campaign snapshot remained protected by the test.
- full `tests/runtime/test_living_world_intelligence.py` after the wake-fixture and serialization repairs: 8 passed, 1 skipped in 206.95s.
- serialization architecture guard now covers current-state schemas plus 56 registered root owner schemas, including owner types not yet materialized in revision 45.
- `tests/runtime/test_military_logistics.py`: 8 passed after making the authorization-growth test explicitly satisfy the registered treasury-reserve premise; the untouched merged ZIP fails the old fixture identically.

Final `test_changed` and `run_release_suite.py` certification are pending and must be recorded here before packaging.

## 12. Remaining risks / future hardening

1. Legacy aggregate records created before modern provenance cannot be retroactively given exact historical origin without inventing data. New writes must continue to record provenance so this fallback shrinks over time.
2. Operational-order history is now lossless in-operation. If history grows large enough to become a storage/read problem, any future archival design must preserve exact rehydration and current-reference integrity rather than reintroducing tail semantics.
3. Current-order uniqueness is enforced at append/startup boundaries. Hot readers intentionally avoid rescanning the complete durable history on every lookup because that caused O(history x lookup) long-horizon cost. Any future external/import writer must pass startup integrity before gameplay.
4. The causal event rate in the mature revision-45 campaign is higher than older fixtures assumed. Long-horizon tests should continue to guard linear density rather than pinning one historical count forever.
5. Other deterministic future-state transitions should receive the same treatment as causal-event archival and petition compaction: test the staged after-image at the threshold, not only the current saved snapshot.
6. Deployment/hosted CI are outside this local-ZIP audit. A locally certified package is not automatically the deployed runtime.

## Final assessment

The repeated campaign failures had a deeper common cause. The system repeatedly blurred four pairs of concepts:

```text
current identity       vs historical order
issued                 vs delivered/actionable
explicit reference     vs bounded history
exact authority        vs projection/compatibility representation
```

The repair strategy makes those distinctions explicit and testable. The system is therefore materially less dependent on the accidental ordering and size of the current revision-45 save, which is the necessary condition for surviving a much longer persistent campaign.
