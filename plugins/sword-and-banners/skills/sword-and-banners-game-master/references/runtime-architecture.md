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
- the transaction coordinator owns persistence and recovery.
- Git-backed committed state is durable campaign history.

Conversation memory is never the save game.

## Campaign authority

`state/` is mutable committed campaign truth.

`game/` is static rules, schemas, mechanics definitions, historical background, and world data.

`runtime/` is engine and service source.

`/data/runtime` is operational persistence such as WAL, locks, receipts, and recovery metadata. It is not a second campaign truth tree and should not be committed as gameplay state.

## Read path

Every live turn starts with `get_play_context`.

That bounded response should be enough to establish:
- campaign revision and world time;
- player identity/status;
- current scene and pressure;
- player-visible knowledge;
- permitted person/object IDs;
- current command catalog and payload surface;
- runtime limits.

Additional reads use exact IDs returned by fresh context. No repository browsing by guessed identifier is part of the player surface.

## Write path

A normal persistent action follows:

```text
natural-language intent
    -> fresh context
    -> one semantic command
    -> read-only preview
    -> exact command + short-lived attestation
    -> execute
    -> deterministic/stochastic resolution as appropriate
    -> transaction staging
    -> local Git commit
    -> remote push and exact verification
    -> receipt publication
    -> fresh context
    -> narration
```

One semantic command is one write transaction. Multi-step player intent is executed sequentially with a fresh context check between writes.

## Contested actions

Sword differs from a deterministic full-preview model for contested combat.

For battle resolution, personal combat, and siege assault:
- preview validates current revision, payload semantics, authority, and readiness;
- preview does not sample or expose the contested result;
- an execution attestation is still bound to the exact command;
- execute samples/resolves the contested outcome once.

This prevents repeated preview from becoming an oracle for favorable randomness.

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

This makes GitHub useful for:
- durable campaign history;
- OOC audits;
- recovery;
- provenance;
- diagnosis of state changes.

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

The MCP endpoint exposes protected-resource metadata at:
`/.well-known/oauth-protected-resource/mcp`

Production MCP is stateless Streamable HTTP at `/mcp` with bounded request bodies and transport-security restrictions.

## Failure semantics

Fail closed on:
- stale revision;
- unsupported command type;
- unauthorized actor or authority;
- malformed payload;
- invalid/expired preview attestation;
- transaction or remote durability failure;
- ambiguous protected player decision;
- unavailable runtime during live consequential play.

Never turn infrastructure failure into fictional success.
