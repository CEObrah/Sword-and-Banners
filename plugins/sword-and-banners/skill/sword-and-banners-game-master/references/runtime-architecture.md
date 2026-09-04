# Runtime Architecture

Use this reference for OOC DEV architecture, persistence, deployment, and integration work.

**AI orchestration boundary.** ChatGPT should understand the semantic command families as a consequence toolkit for the whole game, but it must not turn them into the story's turn structure. The LLM interprets the player's full natural-language intent, directs the lived scene, decides narrative start/continue/transition/end, and invokes only the exact command family needed when a hard consequence is reached. A command returning successfully is evidence about world truth, never an instruction to stop the scene, recap the packet, or hand control back. Formal scene-session operations persist continuity only; they are not prerequisites for narrative scenes.


## Stack and authority

```text
ChatGPT Project
  -> Sword & Banners GM Skill
  -> Sword RPG Runtime MCP
  -> Railway service
  -> persistent campaign Git checkout + private runtime WAL/receipts
  -> configured Git remote
```

ChatGPT interprets natural language, protects agency/knowledge boundaries, and narrates. The Skill defines operating procedure. MCP exposes bounded reads and semantic writes. The runtime owns mechanics, chronology, authority, conservation, persistence, and causal settlement. Conversation memory is never the save.

`state/` is current mutable campaign truth; `game/` is static rule/reference authority; `runtime/` is executable behavior. An `authority:false` record may index/project exact owners but never replace them.

## Production planner composition

Hosted play layers bounded causal intelligence over the baseline engine without creating a second simulation authority. Exact people, formations, force/population pools, operations, Houses, treasuries, relationships, information, territory, events, equipment, mounts, and logistics remain in their exact owners.

The production chain composes causal living-world settlement, House/institution/polity/world-arc work, cohort development, and player group actions. Bounded work targets and projections are routing mechanisms only. World-arc queue records never become strategic evidence by label alone: materially settled arc work must carry verifiable domain evidence from an exact owner/resource change.

## People and force representation

Use scale-appropriate representations:
- state armies and ordinary House troops: conserved aggregate cohorts and exact persistent formations;
- Inner Walls and House Tang ranks, including ordinary Tang Champions: aggregate cohorts;
- named/important people: exact person sheets;
- a cohort member that becomes individually important: materialize/reclassify exactly one conserved body;
- Wei's personal force: cohort-first at scale; materialize `person-lite` or exact identities only for existing members who become named, exceptional, socially important, specialized, command-relevant, or otherwise individually important.

A formation is assignment/custody, not a duplicate source of people. House Tang may own a formation institutionally while Wei holds current command authority. Cohort splits, merges, replacement, casualties, promotion, and materialization preserve headcount and provenance.

Combat resolution is representation-neutral. Rank-and-file capability comes from the actual cohort skill/attribute distributions and service experience; exact/person-lite commanders, deputies, staff, specialists, and standouts remain separate bounded participants. Registered weapon reach/minimum range, missile range/cadence, finite arrows/bolts, protection, mounts, frontage, terrain, cohesion, doctrine, command, and logistics modify how capability is expressed without replacing it.

Recruitment separates population ownership from occupational background. Population strata conserve bodies; `game/data/mil/recruitment-cohort-profiles.json` owns starting distributions and registered selection; `runtime/sword_runtime/recruitment_campaigns.py` owns player-relevant aggregate candidate campaigns. Selection conditions a distribution rather than granting training gains.

## Chronology, causal work, and wakes

Time advancement settles due work globally by saved due time, priority, and stable event identity. A host cursor advances only after its occurrence settles.

Production chronology also carries a durable global scheduler frontier in `state/runtime.json#scheduler`. `world_time` and `causal_settled_through` must match at every committed boundary. Route-affecting commands mark scheduler reconciliation dirty; otherwise small advances may skip expensive route reconciliation. A recurring seven-day `scheduler_reconcile` host runs inside the same chronological heap, so long skips periodically reconcile newly created/reassigned schedulable owners before later monthly/quarterly/annual work is processed. Reconciliation repairs routing only; domain hosts remain consequence authority. Missing historical routes with already-overdue work fail closed rather than silently erasing elapsed development.

When autonomous settlement reaches a hard causal interruption that cannot lawfully continue without Wei's immediate response, production commits only to that boundary, persists a bounded pending wake, and returns the actually reached time. Durable voluntary decisions such as command offers and commissions settle into their exact owners and surface through unresolved-decision projections without becoming scheduler locks. Broad `advance_time` preview hides future outcomes/timing so preview cannot probe the future.

## Playability throughput

World progression is not sufficient if nothing can reach the player. `runtime/sword_runtime/vitality.py` summarizes active pressure, scheduled work, report paths, player-known information, scene freshness, and wakes. Treat starvation diagnostics as routing defects to investigate, not permission to invent events.

## Bounded read path

Every live turn starts with `get_play_context`. Counts and truncation markers indicate a window, never nonexistence. Continue through dedicated tools such as exact object inspection, command contract lookup, controlled-formation paging, known-information paging, and interaction/report handles rather than broadening ordinary context.

Cold reference data never proves current mutable state or player knowledge.


## Intent and mechanic boundary

The command catalog is a **mechanical consequence registry**. It answers which runtime owner can adjudicate or persist a hard effect after the GM already understands the action. It never defines the set of possible gestures, speech acts, local scene interactions, creative tactics, or ordinary NPC behavior. Unsupported **hard state mutation** fails closed; unsupported ordinary fiction does not.

The public GM may establish reversible scene facts from fresh lawful context. Salient observed local details may be persisted as authority-false scene facts for fresh-chat continuity, but those records have no mechanical-consequence authority. Hard facts are promoted only through their domain authority. Attributed speech proves who said something, not whether the statement is objectively true. This permits lies, misunderstandings, negotiation, jokes, disagreement, and human response without turning narration into a second simulation authority.

## Scene and interaction boundary

`state/scene.json` is presentation state. If its world time/revision does not match current campaign authority, stable operations strip transient claims and build a revision-matched runtime projection from exact current owners and already-triggered player-visible facts.

`interaction_action` is a persistence/continuity surface for Wei-owned social or institutional attempts, not a requirement for ordinary speech. Stable operations validate it and translate it to a bounded routing record. Active conversational threads may represent questions, requests, petitions, offers, proposals, or other response-bearing moves; legacy `active_questions`/question fields remain compatibility subsets. Internal `scene_consequence` transport is never a player-authored raw world-outcome command.

`state/index/active-scene-session.json` is a non-mechanical continuity owner for an established council, audience, briefing, family discussion, negotiation, or other people-centered scene. Its duration boundary is soft. It cannot move attendees or grant authority, and a timer may not dismiss an active council underneath unresolved conversation. Travel, combat, explicit departure, scene completion, or another hard boundary closes the reversible session and abandons unresolved threads rather than silently answering them.

Ordinary NPC speech and reversible local scene facts are distinct from mechanical consequences. `scene_session_action` may persist an attributed clarification, opinion, inference, question, advice, objection, observation, or nonbinding proposal/response from an established present participant, or a salient observed scene fact such as local object placement, room-level positioning, visible reaction, or shared premise. Those records prove only what was observed or attributed in the scene. Formal orders, acceptance/refusal that creates an obligation, appointments, resource transfers, ownership changes, injury, travel, creation or authoritative verification of a hidden factual claim, relationship changes, and other hard consequences still require their authoritative domain owners. Truthful disclosure of an already-existing fact the speaker lawfully knows is ordinary attributed speech; the speech does not independently verify the underlying claim.

Attributed speech and reversible scene facts are stored outside the hot interaction-routing ledger. `state/index/scene-history-head.json` keeps a bounded recent window, while lossless period shards under `state/history/scene-speech/` preserve older observed scene history. Both are `authority:false`; old history is recovered through exact bounded reads rather than loading an ever-growing transcript on every turn.

An interaction attempt does not advance time or fabricate a response. Bare `continue` resumes the live scene/process at the current timestamp. Broad time passage across an active scene requires explicit scene policy. Distinct natural-language stop reasons are alternatives through `wait_policy.any_of`; fields inside one precise clause are conjunctive, while values inside one criterion field are alternatives. This lets the scheduler ignore unrelated notices while stopping on any separately requested material development. Saved standing training/routines settle during ordinary downtime without a special per-call training flag.

## Write path

```text
natural-language intent
  -> fresh context
  -> semantic interpretation and reversible scene realization
  -> mechanic discovery only for hard consequences
  -> one selected mechanical operation / exact contract
  -> read-only preview
  -> exact command + attestation
  -> execute
  -> staged transaction
  -> Git commit + required remote durability
  -> receipt
  -> fresh context
  -> narration
```

One semantic command is one write transaction. This is a persistence invariant, not an action whitelist: one natural-language declaration may preserve scene-only components and proceed through several sequential writes under standing intent, stopping only at a new protected decision.

## Idempotency and recovery

Ready previews bind the exact canonical command to a short-lived attestation. Editing the command invalidates it. An exact already-committed retry may recover its immutable receipt. The WAL uses the partitioned pending/terminal layout only; unrelated files are never adopted as pending work.

A campaign never rewinds committed gameplay transactions. A supplied revision-1 starting save uses a fresh private recovery store; any private receipt claiming a revision newer than current campaign state fails closed.

## Deployment

Railway's persistent volume holds the live campaign checkout and private runtime recovery data. Runtime/game/dependency/deployment changes require deployment; state-only gameplay commits and runtime-neutral docs/Skill/tests/tools should not cause deploy loops.

A Git commit, Railway deployment, MCP schema publication, and ChatGPT connector refresh are different states. Verify each separately. Never expose credentials or secrets.

## Progressive command and human-scale domain layer

`runtime/sword_runtime/api/command_discovery.py` builds the compact per-turn intent-family index. One family is demand-loaded through `get_command_family`, then exact payload guidance is fetched through `get_command_contract`. Do not restore the full operation list or command schemas to every play-context response.

`runtime/sword_runtime/campaign_depth.py` owns the generic human-scale mechanics added above formations: command groups/retinue training, epistemic information delivery, investigations, commissions, commitments and medical treatment. Its reducer hook runs beneath the existing production transaction/wake wrappers so these commands cannot bypass chronology, pending wakes, preview rules or durability.

The new process indexes are routing only. Exact process files remain authority; `by_actor` entries exist so a fresh conversation can rediscover the player's actionable processes without scanning the repository.

## GM-private director projection

Read and result surfaces may expose a bounded `gm_private` layer for the current scene or committed consequence. This is intentionally more informative than Tang Wei's observation projection. The runtime remains the source of truth; the private director layer lets the AI use that truth to stage coherent NPC behavior and combat rather than forcing the narrator to reconstruct everyone from a player-safe summary. Disclosure remains separate: player-facing narration and decision scaffolding must still obey Tang Wei's perception and knowledge boundaries.

Exact established present people may contribute bounded private character, goal, behavior and relationship context before a conversation session exists. The session preserves conversational continuity; it is not an NPC activation switch. Ordinary continuation may therefore contain NPC initiative, interruption, cross-talk, humor, hesitation or departure when grounded in the current scene. Personal-combat results likewise expose a bounded director packet with per-participant alignment, capability/condition, exact start/end position, health/fatigue and causal trace so the AI can stage the resolved fight without guessing. These backstage facts never themselves grant Wei perception or create an additional consequence authority.
