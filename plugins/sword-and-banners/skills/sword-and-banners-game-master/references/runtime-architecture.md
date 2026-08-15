# Runtime Architecture

Use this reference for OOC DEV architecture, persistence, deployment, and integration work.

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
- Sword Manor and House Tang ranks, including ordinary Tang Champions: aggregate cohorts;
- named/important people: exact person sheets;
- a cohort member that becomes individually important: materialize/reclassify exactly one conserved body;
- Wei's personal force: cohort-first at scale; materialize `person-lite` or exact identities only for existing members who become named, exceptional, socially important, specialized, command-relevant, or otherwise individually important.

A formation is assignment/custody, not a duplicate source of people. House Tang may own a formation institutionally while Wei holds current command authority. Cohort splits, merges, replacement, casualties, promotion, and materialization preserve headcount and provenance.

Combat resolution is representation-neutral. Rank-and-file capability comes from the actual cohort skill/attribute distributions and service experience; exact/person-lite commanders, deputies, staff, specialists, and standouts remain separate bounded participants. Registered weapon reach/minimum range, missile range/cadence, finite arrows/bolts, protection, mounts, frontage, terrain, cohesion, doctrine, command, and logistics modify how capability is expressed without replacing it.

Recruitment separates population ownership from occupational background. Population strata conserve bodies; `game/data/mil/recruitment-cohort-profiles.json` owns starting distributions and registered selection; `runtime/sword_runtime/recruitment_campaigns.py` owns player-relevant aggregate candidate campaigns. Selection conditions a distribution rather than granting training gains.

## Chronology, causal work, and wakes

Time advancement settles due work globally by saved due time, priority, and stable event identity. A host cursor advances only after its occurrence settles.

When autonomous settlement reaches a protected player decision, production commits only to that boundary, persists a bounded pending wake, and returns the actually reached time. Broad `advance_time` preview hides future outcomes/timing so preview cannot probe the future.

## Playability throughput

World progression is not sufficient if nothing can reach the player. `runtime/sword_runtime/vitality.py` summarizes active pressure, scheduled work, report paths, player-known information, scene freshness, and wakes. Treat starvation diagnostics as routing defects to investigate, not permission to invent events.

## Bounded read path

Every live turn starts with `get_play_context`. Counts and truncation markers indicate a window, never nonexistence. Continue through dedicated tools such as exact object inspection, command contract lookup, controlled-formation paging, known-information paging, and interaction/report handles rather than broadening ordinary context.

Cold reference data never proves current mutable state or player knowledge.

## Scene and interaction boundary

`state/scene.json` is presentation state. If its world time/revision does not match current campaign authority, stable operations strip transient claims and build a revision-matched runtime projection from exact current owners and already-triggered player-visible facts.

`interaction_action` is the player-facing social/institutional attempt command. It contains only Wei-owned intent. Stable operations validate it and translate it to an internal attempt record. Internal `scene_consequence` records are never exposed as a player-authored command and cannot be used to supply NPC/world outcomes.

An interaction attempt does not advance time or fabricate a response. Waiting uses chronology; a response becomes fact only when an authoritative owner establishes it.

## Write path

```text
natural-language intent
  -> fresh context
  -> one advertised semantic command
  -> exact command contract if needed
  -> read-only preview
  -> exact command + attestation
  -> execute
  -> staged transaction
  -> Git commit + required remote durability
  -> receipt
  -> fresh context
  -> narration
```

One semantic command is one write transaction. Multi-step intent proceeds sequentially and stops at new protected decisions.

## Idempotency and recovery

Ready previews bind the exact canonical command to a short-lived attestation. Editing the command invalidates it. An exact already-committed retry may recover its immutable receipt. The WAL uses the partitioned pending/terminal layout only; unrelated files are never adopted as pending work.

If an established campaign repair removes a previously receipted transaction, record that exact tombstone in `runtime/contracts/transaction-invalidations.json`. Unexplained future receipts fail closed.

## Deployment

Railway's persistent volume holds the live campaign checkout and private runtime recovery data. Runtime/game/dependency/deployment changes require deployment; state-only gameplay commits and runtime-neutral docs/Skill/tests/tools should not cause deploy loops.

A Git commit, Railway deployment, MCP schema publication, and ChatGPT connector refresh are different states. Verify each separately. Never expose credentials or secrets.
