# Sword & Banners: first architecture audit

Audited 11 September 2026, before the repairs described in the [implementation notes](AI_GM_REPAIR_NOTES_20260911.md). Sword is the implementation target; Shinobi was inspected read-only. This report records code evidence, not certification of live gameplay. File line references describe the original audited revision.

## A. Current live architecture and evidence limits

The local Sword commit is `3dfed5a4c6c608ae4736684958c47fa0ac7ce279`; a read-only `git ls-remote origin HEAD refs/heads/main` returned that same commit from `https://github.com/CEObrah/Sword-and-Banners`. Shinobi's local comparison commit is `4bb299fe77c0901f7bd81a2c49cb58e791033d91`. Both working trees started clean. There is no checked-in `.github/workflows/` in this Sword checkout, despite README claims that a workflow runs on pushes.

The actual game client is the ordinary ChatGPT conversation, with the Project and installed GM Skill supplying operating instructions. Neither is the save game. The Skill is `plugins/sword-and-banners/skill/sword-and-banners-game-master/`, including `SKILL.md`, `agents/openai.yaml`, references, and Project instructions. The backend does not call an LLM: intelligence must enter through the external GM's tool choices and proposals.

The authenticated streamable HTTP MCP server (`runtime/sword_runtime/api/mcp.py`) calls the same Python operations used by REST. It is not a separate remote simulation hop. Production composes `ReconnaissanceAwareOperations` over the operation subclasses, `ProductionSwordRuntime`, `CommandRoutedProductionPlanner`, and the hosted planner mixins (`api/app.py:131`, `service_runtime.py:220`, `production_runtime_planner.py:29`). This differs materially from tests that construct only `SwordRuntime` or the intermediate production planner.

Railway builds source and starts `PYTHONPATH=/app/runtime python -m sword_runtime.branch_bootstrap`. Bootstrap reconciles the image with a campaign checkout on durable storage, then loads the ASGI app. Runtime Python comes from the deployed image; campaign JSON comes from the configured checkout. Private WAL, receipts and lock files live in a separate configured runtime directory. A source edit, source ZIP, installed Skill, MCP tool catalog and deployed image are distinct artifacts.

`tools/package_release.py` makes a deterministic repository ZIP and can extract/byte-verify it, then run small smoke guards. It includes the current `state/` snapshot. Uploading that ZIP as Project knowledge does not deploy Python or create a fresh save. The Skill folder is the instruction artifact to install; the runtime must separately be deployed. OpenAI's [connection and testing documentation](https://developers.openai.com/plugins/deploy/connect-chatgpt) also treats connecting and testing the MCP/plugin in ChatGPT as its own step.

No authenticated Railway instance, installed ChatGPT Skill, connector catalog, running campaign endpoint or new gameplay transcript was supplied/observed. Their actual versions and behavior remain unverified. Historical claims in docs are evidence to investigate, not proof that these local files are live.

## B. Actual turn lifecycle

1. The GM loads its Skill and calls `get_play_context(skill_contract_token=...)` each turn.
2. MCP checks the Skill token, checks local deployment compatibility, builds the production context and compacts it into the GM scene packet (`api/mcp.py:372`). The campaign ID and expected revision come from the server's single configured root.
3. The GM interprets intent. Reversible dialogue/performance can proceed without mutation. For a consequential action it discovers a mechanic family and exact contract.
4. `preview_command` builds a player gameplay envelope at the expected revision. Surface operations validate/translate it. Deterministic previews plan and validate staged writes; contested previews hide the outcome (`service_runtime.py:317`).
5. `execute_command` checks the signed, expiring preview attestation and sends the exact envelope to operations/runtime. Planning produces a write set and validator. The coordinator locks, checks revision, prepares WAL, validates, replaces files, commits Git, verifies durability and records a receipt (`tx/coordinator.py:361`).
6. The GM uses the committed result, refreshes context between consequential writes, and narrates. A turn can require several such transactions. There is no whole-turn commit.
7. A later chat using the same endpoint reaches that same save. A new chat/Project is not a new campaign.

Conversation traces through `interaction_action`/`scene_session_action` to scene history; substantive responses can route through specific institutional/command handlers. Combat traces through `personal_combat`, exact physical resolution and persisted injury/body state. Army orders trace through command authority, order/delivery owners, movement and time settlement. Politics routes through specific polity/House/strategic handlers. Travel owns route, elapsed time and movement consequences, including interruption. These are different domain paths sharing transaction infrastructure, not one universal narrative interpreter.

## C. AI versus runtime responsibility

| Classification | Current implementation | Consequence |
| --- | --- | --- |
| Appropriate AI ownership | Dialogue, pacing, reversible scene behavior, natural-language intent, presentation and private knowledge filtering in the Skill | The AI is more than a text formatter during scenes |
| Appropriate runtime ownership | Exact bodies, contact/anatomy, inventory, money, formations, physical orders, chronology, persistence | Mechanical outcomes can remain authoritative |
| Over-scripted | Numeric tactical selection; deterministic strategic plans and withdrawal; bespoke campaign/contact/family/institutional response handlers | NPC decisions and generalship are often selected by Python; the model does not author much consequential behavior |
| Too unconstrained | Generic `relationship_change` accepts player-sourced delta/basis without proving a causal event; semantic prose assertions cannot be validated merely by JSON shape | A successful command need not establish that its social cause was earned |
| Missing bridge | GM-authored cognition is mostly readable but not writable; scene continuity explicitly cannot establish motive or relationship truth | Important invented suspicion, ambition or plan can remain only in conversation memory |

No defensible percentage of AI-driven gameplay can be inferred from LOC or command counts. The boundary is qualitative: rich AI performance, substantial runtime-selected durable behavior. The mechanic catalog explicitly says it is not an action whitelist, but missing generic durable semantics still constrains actual agency.

## D. State authority map

| Category | Current owner / allowed path | Retrieval and duplication risk |
| --- | --- | --- |
| Campaign identity/revision | `state/meta.json`, coordinator | Context; one configured root, no public create/select API |
| Time | Meta time plus `state/runtime.json` frontier, hosted `time_integration.py` orchestration | Context/scheduler; copies must advance coherently |
| Player/NPC identity and location | Exact owner index to `state/player.json`, `state/char/`, person-lite/materialized people | Scene projection and sheets; aliases and scene caches must not become independent authority |
| Injury/death/capability | Exact person anatomy, physiology, combat state; physical resolver | Combat/private sheets; several representations require consistent derived projections |
| Money/equipment/material | Wallet, inventories, equipment owners and exact domain operations | Context/exact reads; descriptive loadouts are not new stock |
| Troops/positions/orders | Population → force pool → persistent formation → temporary operation; order/delivery owners | Controlled-force and operation projections, exact reads |
| Relationships | `state/relationships.json`, relationship/domain handlers | Private scene/person edges omit fields written by generic relationship changes |
| Knowledge | `state/information/` claims/holders/evidence | Player-known claims versus explicitly private cognition |
| Scene memory | Active sessions, attributed speech/facts/continuity history | Bounded recent windows and exact retrieval; marked non-mechanical |
| NPC goals/beliefs/memories | Character fields and domain-specific processes, where present | Private sheets/cast; no general AI-authored update path |
| World reference | `game/data/` and rules | Cold search; not current mutable state or automatic player knowledge |

## E. AI-created persistence

The AI can persist player attempts, attributed speech, salient reversible scene facts, and derived literary continuity with evidence. Specific commands can create information claims, player commitments, relationships and institutional events. It cannot generally establish a new NPC belief, grievance, goal or political scheme without a bespoke handler or an inappropriate use of another authority.

`scene_session_action` validates presence and references; raw `scene_consequence` is rejected on the player surface (`api/stable_operations.py:1080`). This is a useful bounded bridge for continuity, but the Skill expressly makes it authority-false for motives and relationships. `belief_state` and `memory_state` have read sites without a corresponding general writer. An NPC's promise is not equivalent to the existing player-obligor commitment operation. Rumor text can be recorded as attributed speech/claim; it must not become proof that grain wagons actually disappeared.

Existing retention is mostly bounded projection windows and sharded history, not a complete cognition lifecycle. A repair should support selective creation, revision and resolution with evidence and explicit capacity, not record every gesture. It must distinguish the canonical fact “Zhou suspects theft” from the unproven claim “theft occurred.”

## F. NPC intelligence and relationship history

Private character/behavior/goal packets and relationship edges are already exposed (`api/warfare_operations.py:136`, `:169`, `:223`, `:373`). That gives the GM useful material for distinct voices and motives. Much of it is seeded/static or changed by deterministic handlers, rather than authored through an AI proposal.

The generic relationship writer stores `value`, `evidence_refs`, `last_basis_ref`, and `last_changed_at` (`engine.py:6327`), but the private projections select `history`, `current_tension`, and `dimensions` instead (`api/warfare_operations.py:360`, `:474`). Thus even existing causal references can disappear from the GM packet. Equal scores cannot yield history-sensitive behavior when the cause is omitted.

NPC response envelopes permit AI reasoning, but consequential responses frequently remain runtime-selected. Character evolution needs an explicit persistence path; prose-only evolution will not reliably survive a new chat.

## G. Combat AI

The model interprets player intent into bounded combat inputs; exact runtime resolution owns contact, positioning, armor, anatomy, physiological impairment, time and death. This is the right authority split for physical consequences. The Skill correctly forbids announcing an uncertain kill before execution.

However, `combat_tactics.py:91` selects team plans, leaders and roles by numeric scores and policy branches, and runtime combat doctrine/action selection determines much NPC response. There is no general AI tactical-plan proposal round trip. The runtime therefore owns more tactical reasoning than the requested philosophy intends. Preserve existing physical primitives; later add constrained actor intentions before resolution instead of replacing injury logic with named attack exceptions. This audit does not certify every anatomy→capability path without live evidence.

## H. Military and political AI

`strategic_war_planning.py:404` builds interstate plans; `:360` decides contingency withdrawal; command-cycle/campaign-contact mixins select many institutional responses. Forces, hierarchy, route, supply, orders and timing have extensive physical representation, but strategic decisions are heavily algorithmic. An AI can narrate rationale yet cannot generally substitute an independently reasoned enemy scheme through the current boundary.

Repair in stages: first persist intentions and causes safely; later accept AI-authored bounded orders/plans referencing actual actors, resources and knowledge, with execution remaining runtime-grounded. Do not remove deterministic offscreen fallback before a reliable GM decision handoff exists.

## I. MCP contract, transactions and call volume

MCP tool schemas are generated from Python tool signatures/Pydantic models. Semantic payloads are separately described by `COMMAND_TYPES`, `COMMAND_PAYLOAD_KEYS`, input guidance, surface validators and Skill prose; that duplication can drift. The Skill fingerprint is generated only from Skill files (`tools/sync_gm_skill_contract.py`), not the runtime or MCP contract. Static service versions (`0.3.0`, package `1.0.0`) do not identify a build.

Typical inferred call budget: a scene-only turn needs one context read; a first use of a mechanical operation adds family discovery, contract read, preview and execute, normally followed by context (about six total). Each further operation adds roughly three calls, plus relevant exact reads. These are code-derived counts, not measured live telemetry. There is no evidence that ordinary turns universally need dozens, but compound turns can grow substantially.

The coordinator provides real single-command revision checks, WAL recovery and durable idempotency. Two important holes precede that boundary:

* The shared mutable planner resets its caches/writes during preview and execution outside the commit lock (`engine.py:7657`, `:7704–7719`; `service_runtime.py:334`). Concurrent requests can interfere during planning.
* Surface duplicate lookup re-runs current scene validation before looking up an immutable receipt (`api/stable_operations.py:1722`). A retry of a successful scene close or resolved thread can be rejected because that successful action changed the precondition.

One semantic command commits coherently. Several independent commands constituting a turn do not. Do not claim whole-turn atomicity; batch only changes sharing a clear authority/validation boundary in a later repair.

## J. Fresh context

The context does substantial useful work: it checks scene timestamp/revision, reprojects stale scenes from exact owners, bounds private cast, separates present/nearby/referenced people, exposes active combat and decisions, and provides truncation markers/exact read routes. It does not reconstruct the save from narration.

But it is not a locked snapshot. Operations perform many independent file reads while `AtomicManifestPersister` replaces individual files and writes meta last (`tx/persistence.py:12–18`, `:54–64`). A reader can see mixed old/new state even when meta appears unchanged. A before/after revision check alone would not fix this window. Social context also lacks the general cognition bridge and drops relationship cause fields. Context freshness and semantic completeness are separate requirements.

## K. Deployment, versions and fresh campaign isolation

The supplied save is already campaign `sword-banner-tang-wei-main`, revision **45**, time **244-BCE-12-21T12:00:01+08:00**. Its release lineage is `sanyou-campaign-handoff-r45-20260908`. These are observations of the supplied files, not a requirement that gameplay remain at revision 45.

Code uses baseline-scoped campaign branches and recovery directories, contradicting README's statement that no separate campaign branch is required. Release state verification pins the shipped snapshot; ordinary live state legitimately advances beyond it. A genuinely fresh campaign requires an explicitly selected seed, identity, isolated checkout and recovery store. There is no MCP new-campaign operation. Do not present a new ChatGPT chat or an old ZIP snapshot as a clean new game.

`deployment_attestation.py` compares Railway's advertised image SHA with local checkout/tracking refs and permits state-only advances. This is useful but cannot prove the remote tracking ref is current without fetching. Missing image SHA is accepted as developer-compatible and then context reports `deployment_compatible: true`. The context omits the existing image/check-out SHA detail. Package and live build need comparable runtime/MCP/schema/Skill identities plus honest unknown status.

## L. Test quality and Shinobi comparison

AST inventory: Sword has 284 test files / 1,551 test functions; Shinobi 164 / 1,116. These counts are descriptive, not confidence scores.

| Class | Representative evidence | Disposition |
| --- | --- | --- |
| High-value mechanics/invariants | Anatomy/penetration, exact material conservation, receipt nested-number serialization | Run specific tests for changed authority |
| High-value persistence | Real Git coordinator crash/retry/rollback; small deployment source-vs-state repositories | Keep; select relevant boundaries |
| Brittle/misleading as behavior evidence | `test_skill_fiction_rendering_contract.py`, `test_narrative_quality_hard_gate.py` assert literal prose exists | Treat only as instruction lint; live narration remains untested |
| Duplicative contract assertions | Delivery and Skill tests repeat source-string/fingerprint checks | Consolidate around behavioral contract checks when touched |
| Fixture-sensitive | Sword `conftest.py` clones the current campaign; helpers can silently relocate special test people | Prefer minimum fixed fixtures for new regressions |
| Expensive/useful infrequently | 365-day hosted/world progression, broad release/replay suites | Deliberate release questions only |
| Better in ChatGPT | NPC initiative, tactics, pacing, tool choice, knowledge leaks, cross-chat recall | Short live transcript tests |

Neither inspected test tree exercises an actual MCP `ClientSession`/`tools/list`/`call_tool` round trip. Some “delivery chain” tests inspect adapter source strings. Sword's changed-path router can select broad world/performance tests, so it is not automatically cheap. No expensive suite was run for this audit.

Shinobi has stronger locked planning and plan-base verification in `api/operations.py:1305–1333`, and missing Railway SHA is unhealthy under production markers. Its context lock ends before some subsequent state reads, so it is not a complete snapshot solution. Its immutable real-failure fixture (`tests/current/play_failure_fixture.py`) is a better regression pattern. Both games share authority-false scene memory and prose-lint limitations. No broad port is warranted yet.

## M–N. Ranked failures and repair order

1. **Read/planner isolation:** guard the complete public operation and plan lifecycle against concurrent campaign writers; use the existing lock/revision system, not event sourcing.
2. **Retry identity before changed preconditions:** authorize actor and recover the exact immutable receipt before revalidating an already-applied scene action.
3. **Honest release identity:** expose comparable source/runtime/MCP/schema/Skill fingerprints; fail clearly for missing production identity; correct deployment docs.
4. **AI-authored durable cognition:** add a bounded, evidence-linked NPC cognition proposal/commit path and private rehydration. Preserve hard authority and player mental agency. Include existing relationship causes in context.
5. **Fresh campaign workflow:** design explicit isolated creation from an agreed seed; never silently reset this supplied save.
6. **Coherent compound turns:** extend transactions for related proposals/consequences after the smaller bridge is proven.
7. **AI tactical/strategic decisions:** add intention handoffs over conserved actors/resources, preserving physical adjudication and a fallback for offscreen progression.
8. **Domain consistency guided by transcripts:** time, injury/capability/death, resources and troop/order/location regressions; consolidate misleading tests as touched.

Items 1–4 are the first bounded implementation pass. This is not a claim that the remaining architecture is reliable enough for sustained gameplay.

## O. Targeted local validation

Use a disposable test environment and fixed/minimal fixtures where possible. Run syntax/JSON checks, Skill fingerprint synchronization, small deployment identity tests, synchronized reader/writer and simultaneous planner tests, exact retry-after-scene-change tests, and one real production-operations cognition commit/reload/private-redaction regression. Check stale revision, rejected unknown evidence/player mental writes, duplicate execution, unchanged time/material state, and rollback. Extract/byte-verify the actual ZIP. Add one actual in-process MCP protocol smoke if the declared SDK is available. Do not run all tests, broad changed-path selections, yearly simulation or AI evaluations.

## P. Live ChatGPT validation

Deliver matching source and Skill artifacts with a manifest and an explicit deployment handoff. First compare live version output to that manifest and confirm intended campaign identity/revision. Resume the existing campaign only after confirming its actual conditions; use an isolated agreed baseline for dangerous combat or troop tests.

1. Have a present NPC form a plausible, evidence-grounded suspicion or personal plan. Continue several beats, start a separate chat on the same endpoint, and ask about it. The NPC must remember the cause; a suspicion must remain uncertain and private unless disclosed.
2. Resolve a consequential scene action, then exercise an exact retry if a tool response is interrupted. One effect and one revision advance; the same receipt returns.
3. Continue through two chats and compare fresh campaign revision, location, health, inventory and scene participants. Stale commands should request refresh, never silently overwrite.
4. Attempt creative compound combat, then treatment/next action. Narrated hit/miss, anatomy and ability must match committed outcomes; no throat-specific scripted shortcut.
5. Give a conditional combined-arms order involving real units and terrain. Observe whether commanders reason convincingly; all bodies, movement, time and resources must remain conserved.

Return transcript, OOC QA, tool errors/receipts, version output, campaign revisions and any unexpected state. Local checks cannot establish Skill interpretation, actual connector schema freshness, NPC performance or sustained cross-chat quality. Stop at this live handoff rather than simulating a long campaign in Codex.
