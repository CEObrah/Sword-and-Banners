# Runtime Architecture

Use this reference for OOC DEV architecture, deployment, durability, and integration questions.

## Separation of responsibility

The production stack is:

```text
ChatGPT Project
    -> Sword & Banners Game Master Skill
    -> Sword & Banners Runtime MCP App
    -> Railway production service
    -> persistent /data/campaign Git checkout
       + private /data/runtime WAL, locks, receipts, recovery data
    -> GitHub private repository main branch
```

Responsibilities remain separate:

- ChatGPT interprets natural-language intent, protects agency/knowledge boundaries, and narrates.
- The Skill defines GM operating procedure and presentation discipline.
- MCP exposes bounded read tools and semantic write tools.
- The runtime validates authority, chronology, ownership, conservation, and mechanics.
- The production living-world layer selects among lawful exact assets, preserves chronological causal scheduling, and records bounded non-authoritative operational evidence.
- The transaction coordinator owns persistence and recovery.
- Git-backed committed state is durable campaign history.

Conversation memory is never the save game.

## Campaign authority

`state/` is mutable committed campaign truth.

`game/` is static rules, schemas, mechanics definitions, historical background, and world data.

`runtime/` is engine and service source.

`/data/runtime` is operational persistence such as WAL, locks, receipts, and recovery metadata. It is not a second campaign truth tree and should not be committed as gameplay state.

A saved record may explicitly declare `authority: false`. Such a record can be a persisted projection, index, or operational-memory surface without replacing the exact authoritative owners it references.

## Production living-world layers

The baseline domain mechanics remain in `runtime/sword_runtime/engine.py`. Hosted play layers additional intelligence without creating a second simulation authority:

```text
RepositoryCommandPlanner
    -> LivingWorldSwordPlanner
       bounded operational memory
       objective-fit exact formation selection
       concurrent state-response capacity
       learned battle evidence
    -> CausalLivingWorldSwordPlanner
       globally chronological causal catch-up
       callback-created host preservation
       resumable high-salience wake boundaries
       semantic event provenance
    -> ProductionLivingWorldSwordPlanner
       hard assignment/custody exclusion
       exact commander availability
       physical operation-status truthfulness
       final provenance normalization
```

Exact formations, people, state force pools, operations, Houses, treasuries, relationships, reputation, information, territory, and logistics remain authoritative in their existing owners. Operational memory is bounded evidence only.

## Chronological causal scheduling

Production time advancement processes due causal events globally by exact due time, priority, and stable event ID rather than settling one host's entire catch-up horizon before another host.

Each due occurrence sees the world after all earlier causal occurrences in the same command. A callback that lawfully creates a new host or event is re-read from the staged runtime and enters the same bounded queue. No state directory scan is required.

The per-command causal queue is bounded. A host's `resolved_through` is advanced only after that exact occurrence actually settles. `safe_through` remains a causal horizon, not permission to erase eligible work.

## High-salience wake boundaries

Broad time advancement may reach a state where autonomous settlement would cross a protected player-facing decision. The primary current case is an exact player-commanded interstate formation making enemy contact before autonomous battle resolution.

Production then:
1. commits only through the causal contact instant;
2. persists a bounded `pending_wake` in `state/runtime.json`;
3. suspends the exact causal host/event before the irreversible battle step;
4. publishes the actual reached world time, not the originally requested later time;
5. exposes only player-safe wake facts and the temporarily legal response command subset through fresh play context.

The wake is not a failed simulation. It is committed world progress up to a player-agency boundary.

An explicit lawful response may alter command, movement, mobilization, supply, assignment, or operation state. If the player explicitly continues the contact through time advancement, the runtime acknowledges that exact wake and resumes the suspended causal route. Preview and execute enforce the same temporary command-availability contract.

## Operational memory and autonomous assignment

`state/world/operational-memory.json` is lazily created with `authority: false`.

It may remember bounded evidence such as:
- state operation capacity;
- active/recent autonomous operation refs;
- formation role and target strength;
- readiness snapshots;
- training reviews and replacements;
- deployments;
- battle wins/losses/casualties;
- recent causal event refs.

Autonomous state assignment can consider exact readiness, fatigue, logistics, commander capability/location, objective-role fit, current commitments, and prior performance. Existing active operation commitments are hard exclusions, not score penalties. A commanderless formation is not autonomous deployment-ready. An autonomous operation is not `active` unless its exact participating formations are mobilized and physically co-located at the operation location.

Standing formations continue to use Sword's existing conserved recruitment/reconstitution/training mechanics. The intelligence layer does not award free NPC competence or invent replacement generals.

## Read path

Every live turn starts with `get_play_context`.

That bounded response should be enough to establish:
- campaign revision and world time;
- player identity/status;
- current scene and pressure;
- player-visible knowledge;
- permitted person/object IDs;
- current command catalog and payload surface;
- runtime limits;
- any committed player-facing wake boundary and temporary response-command availability.

Additional reads use exact IDs returned by fresh context. No repository browsing by guessed identifier is part of the player surface.

`state/scene.json` is a player-facing projection, not mechanical authority. A scene projection is fresh only when both its `world_time` and `projection_revision` match `state/meta.json`. If either differs, the service strips transient scene claims, unresolved decisions, pressures, and scene-derived read permissions rather than carrying false context forward.

## Write path

A normal persistent action follows:

```text
natural-language intent
    -> fresh context
    -> one semantic command
    -> read-only preview
    -> exact command + short-lived attestation
    -> execute
    -> deterministic/stochastic/causal resolution as appropriate
    -> transaction staging
    -> local Git commit
    -> remote push and exact verification
    -> receipt publication
    -> fresh context
    -> narration
```

One semantic command is one write transaction. Multi-step player intent is executed sequentially with a fresh context check between writes.

A time-advance transaction may complete earlier than its requested horizon when it commits a high-salience wake boundary. The committed receipt and refreshed context define the actual elapsed result.

## Contested and hidden-future actions

Sword does not expose outcomes during preview when doing so would make preview an oracle.

For battle resolution, personal combat, siege assault, and broad time advancement:
- preview validates current revision, payload semantics, authority, and currently known availability;
- preview does not sample or expose a contested result or future autonomous contact;
- an execution attestation is still bound to the exact command;
- execute resolves the contested/causal path once.

Repeated preview must never be usable to search for favorable randomness or hidden future events.

## Preview attestation

A ready preview returns:
- the complete canonical command record;
- a short-lived HMAC attestation bound to that exact command digest.

Execution of a new command requires both unchanged. Editing command type, payload, revision, actor, campaign, request ID, timestamp, or other envelope data invalidates the proof.

An exact already-committed retry can return its immutable duplicate receipt without requiring a still-live attestation.

Never expose or request the server preview-secret environment value.

## Remote Git durability

Production uses `GitRemoteDurability` inside the transaction coordinator. A write is not considered committed player-facing campaign truth merely because a local commit exists.

The production sequence verifies the configured remote branch before publication of the receipt. Push failures remain recoverable transaction failures rather than silent best-effort replication after success.

This makes GitHub useful for durable campaign history, OOC audits, recovery, provenance, and diagnosis of state changes.

## Explicit repair and receipt invalidation

Runtime receipts are immutable external evidence. If OOC DEV deliberately repairs campaign history by restoring state behind a previously receipted transaction, the old receipt does not disappear.

The exact removed transaction must be tombstoned in `runtime/contracts/transaction-invalidations.json`. Production startup recovery scans for receipts claiming revisions ahead of current campaign state and accepts only exact registered invalidations. An unexplained future receipt fails closed. An invalidated request ID is permanently reserved and cannot be replayed.

This protects against a repaired campaign silently resurrecting a removed transaction through idempotent retry.

## Persistent-volume recovery

Railway's build filesystem is ephemeral. The persistent volume contains the live campaign checkout and runtime recovery data.

Bootstrap behavior is fail closed:
- clone when the campaign checkout is absent;
- fetch the configured branch;
- fast-forward when remote is ahead and checkout clean;
- preserve a clean local-ahead commit so coordinator recovery can finish a transaction;
- refuse dirty conflicting checkout;
- if repository history has been replaced, adopt the new remote lineage only when the clean local and remote committed `state/` trees are identical;
- if campaign authority differs across divergent lineages, stop for deliberate repair.

Never force-push campaign history as an automatic recovery strategy.

## Deployment triggers

Source/rule/config changes should redeploy Railway.

Gameplay changes under `state/**` must not trigger a deployment loop. Railway watch patterns therefore include every repository change by default and exclude only `state/**` campaign commits. This keeps the persistent checkout synchronized with `main` after Skill, docs, tests, tools, or source changes while avoiding gameplay redeploy loops.

The running service already owns the state mutation that produced those commits.

## OAuth and MCP

The ChatGPT MCP app uses OAuth with separate read/write scopes:
- `sword:read`
- `sword:write`

Read tools require the read scope. Execute requires write scope as well.

Access tokens are verified for issuer, audience, signature, expiry, allowed subject, scopes, and optional client allowlist.

The MCP endpoint exposes protected-resource metadata at `/.well-known/oauth-protected-resource/mcp`.

Production MCP is stateless Streamable HTTP at `/mcp` with bounded request bodies and transport-security restrictions.

## Failure semantics

Player-facing failures use stable low-information codes rather than raw Git output, server paths, exception strings, or credentials.

Fail closed on:
- stale revision;
- stale scene projection;
- unsupported command type;
- temporarily unavailable command during a pending wake;
- unauthorized actor or authority;
- malformed payload;
- invalid/expired preview attestation;
- unexplained future receipt after a repair;
- transaction or remote durability failure;
- ambiguous protected player decision;
- unavailable runtime during live consequential play.

Never turn infrastructure failure into fictional success.
