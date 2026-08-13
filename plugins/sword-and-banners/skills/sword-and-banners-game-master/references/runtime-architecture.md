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

- ChatGPT interprets natural-language intent, protects agency/knowledge boundaries, and narrates.
- The Skill defines GM operating procedure and presentation discipline.
- MCP exposes bounded player-safe reads and semantic writes.
- Stable operations translate surface intent into runtime-owned commands without letting caller prose become world outcome.
- The runtime validates authority, chronology, ownership, conservation, and mechanics.
- The transaction coordinator owns persistence, remote durability, receipts, and recovery.
- Git-backed committed `state/` is durable campaign history.

Conversation memory is never the save game.

## Campaign authority

`state/` is mutable committed campaign truth. `game/` is static rules/world authority. `runtime/` is executable source. `/data/runtime` contains operational WAL/locks/receipts and is not a second campaign truth tree.

A saved record may explicitly declare `authority: false`. Such a record can route, index, or project exact owners but cannot replace them.

## Production living-world layers

Baseline domain mechanics remain in `runtime/sword_runtime/engine.py`. Hosted play layers bounded causal intelligence without creating a second simulation authority:

```text
RepositoryCommandPlanner
    -> LivingWorldSwordPlanner
    -> CausalLivingWorldSwordPlanner
    -> ProductionLivingWorldSwordPlanner
    -> CampaignEventPlayerGroupActionPlanner
```

Exact formations, people, force pools, operations, Houses, treasuries, relationships, reputation, information, territory, event registries, and logistics remain authoritative in their exact owners.

## Chronological causal scheduling and wakes

Time advancement settles due causal work globally by due time, priority, and stable event identity. A host's progression cursor advances only after its exact occurrence settles.

When autonomous settlement would cross a protected high-salience player decision, production commits only to that causal boundary, persists a bounded `pending_wake`, suspends the irreversible continuation, and returns the actually reached time. Refreshed play context defines the legal response set.

Broad `advance_time` is outcome-hidden during preview so preview cannot probe future contacts or event timing.

## Read path and bounded context

Every live turn starts with `get_play_context`.

The ordinary handoff is intentionally bounded. Counts and `*_truncated` markers are completeness signals, not lifetime ceilings. When a hot window truncates, continue through dedicated read tools rather than making every turn a world dump:
- `get_command_contract` for one advertised semantic command;
- `list_controlled_formations` for paged controlled formations;
- `list_known_information` for saved player-known claims;
- `list_interaction_handles` for triggered player-visible response/message handles;
- exact `inspect_game_object` rehydration where current authority/knowledge can be revalidated;
- bounded cold `search_world_reference` for reference identity/background only.

Cold reference data never proves current mutable state.

## Scene projection lifecycle

`state/scene.json` is an authored player-facing projection, not mechanical authority.

A stored authored scene is fresh only when both its `world_time` and `projection_revision` match `state/meta.json`. If either is stale, production stable operations:
1. strip its transient cast/access/pressure/decision/read-permission claims;
2. retain its previous summary only as a clearly presentation-only continuity anchor;
3. build a revision-matched `fresh_runtime_projection` from exact current owners, already-triggered player-visible event-registry facts, and typed player interaction attempts.

The runtime projection never promotes old prose into current presence, access, protocol, staffing, opportunity, or unresolved status.

## Typed player interaction boundary

Social, court, petition, audience, report, and institutional attempts use a player-facing `interaction_action` contract.

The surface may contain only player-owned intent: exact visible target/process refs, action, player statement, posture, and exact controlled accompanying formations. It rejects caller-supplied NPC/world outcomes such as reaction, acceptance, access, rank, appointment, vacancy, or permission.

`interaction_action` is intentionally a **surface-only** semantic command. Stable operations validate it, preserve the original surface command digest, and translate it into a typed attempt-only compatibility record for the existing engine reducer. New player-facing raw `scene_consequence` writes are blocked; the legacy reducer remains only for replay/backward compatibility and exact already-committed duplicate recovery.

An interaction attempt does not advance time or fabricate a reply. Waiting uses `advance_time`. External response becomes fact only when another runtime authority actually establishes it, for example an already-triggered causal event/message owner.

This distinction prevents player or model prose from silently becoming NPC consent, office, access, or institutional outcome.

## Write path

A normal persistent action follows:

```text
natural-language intent
    -> fresh context
    -> one advertised semantic command
    -> exact command contract when needed
    -> read-only preview
    -> exact complete command + short-lived attestation
    -> execute
    -> transaction staging
    -> local Git commit
    -> required remote push/verification
    -> receipt publication
    -> fresh context
    -> narration
```

One semantic command is one write transaction. Multi-step intent is sequential with fresh context after each commit.

## Contested and hidden-future preview

Battle, personal combat, siege assault, and broad time advancement do not expose their outcomes during preview. Preview validates readiness/authority without sampling a result. Execute resolves the causal or contested path once.

Repeated preview must never be usable to search for favorable randomness or hidden future events.

## Preview attestation and idempotency

A ready preview returns the complete canonical command record plus a short-lived HMAC attestation bound to its exact digest. Editing any envelope field invalidates the proof.

Surface translations must preserve exact request identity. Typed interaction translation embeds the original surface digest so different surface commands cannot collapse into the same translated receipt identity after normalization.

An exact already-committed retry may recover its immutable duplicate receipt without a still-live attestation. New legacy raw-scene writes remain blocked while exact historical duplicates remain recoverable.

## Remote Git durability

Production uses `GitRemoteDurability` inside the transaction coordinator. A local Git commit alone is not published as successful campaign persistence. The configured remote branch must contain and verify the exact transaction commit before the receipt is published.

While the campaign writer lock is held, a clean checkout may fast-forward across remote commits only when their paths are explicitly runtime-neutral. Current neutral classes are Skill/docs/tests/tools/workflow/README changes. Runtime/game/dependency/deployment changes require the running code lineage to remain synchronized by deployment rather than being silently adopted mid-process.

## Repair and receipt invalidation

Runtime receipts are immutable external evidence. If OOC DEV deliberately repairs campaign history behind a previously receipted transaction, register the removed transaction in `runtime/contracts/transaction-invalidations.json`. Unexplained future receipts fail closed; invalidated request IDs remain reserved.

## Railway checkout and deployment

Railway's build filesystem is ephemeral. The persistent volume contains the live campaign checkout; `/data/runtime` contains recovery data.

Bootstrap clones when absent, fast-forwards a clean remote descendant, preserves a clean local-ahead transaction for coordinator recovery, refuses dirty conflicting checkouts, and adopts intentionally replaced Git history only when committed campaign authority is byte-equivalent.

`railway.toml` deploy watch policy follows the runtime-neutral boundary:
- **redeploy:** runtime, game, dependency, and deployment/config changes;
- **no redeploy loop:** gameplay `state/**`, Skill, docs, tests, tools, workflow-only, and README changes.

State-only gameplay commits are already made by the running writer and must not restart the service.

## OAuth and MCP

The ChatGPT MCP app uses OAuth with `sword:read` and `sword:write`. Read tools require read scope; execute requires both.

Production MCP installation consists of the base tools in `api/mcp.py` plus bounded continuation/contract tools in `api/mcp_extensions.py`, installed by `create_app_from_env()` before mounting the MCP app.

A successful Railway deployment is not proof ChatGPT has refreshed a changed MCP tool schema. After adding/renaming tools, verify the connected Sword runtime actually exposes the new list. If not, refresh or republish the custom app/action snapshot before claiming integration is complete.

Never expose OAuth secrets, the preview secret, Git tokens, or credential-bearing transport errors.
