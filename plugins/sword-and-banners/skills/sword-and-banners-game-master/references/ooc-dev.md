# OOC Development

Use this reference for source changes, rules changes, runtime work, deployment, MCP/OAuth integration, Skill updates, migrations, repairs, audits, and release work.

OOC DEV is not gameplay. Development activity does not advance campaign time and does not authorize silent changes to campaign truth.

## Establish current source truth

Before changing the repository:
1. inspect the current target branch/head;
2. read the files that actually own the behavior;
3. check recent relevant commits when behavior may have changed;
4. distinguish current production code from archived/retired execution paths;
5. preserve existing strong invariants unless the task explicitly requires changing them.

This game is self-contained. Never inspect, import, synchronize, or infer implementation truth from another game repository, runtime, campaign, or Skill. Reusable design principles must be implemented independently inside Sword & Banners and verified against Sword authorities.

## Separate code, game data, Skill, and campaign repair

Classify each proposed change:

**Runtime/source change**: executable behavior, API, transactions, scheduler, combat, warfare, validation, autonomy.

**Game/rule/data change**: static mechanics, schemas, world content, economy, locations, doctrine, historical background.

**Skill/presentation change**: GM procedure, narration, player UX, choice framing.

**Campaign truth repair**: correcting a committed state fact that is actually wrong.

Never hide a campaign repair inside a source refactor. Never patch `state/` because a test or narration is inconvenient. Confirmed bad campaign state must use an explicit repair or migration mechanism with provenance, validation, and narrow scope.

If a deliberate repair restores campaign state to a revision earlier than an already-issued runtime receipt, register that exact removed transaction in `runtime/contracts/transaction-invalidations.json`. Never delete or reuse the old request ID. Production recovery fails closed on unexplained future receipts.

## Preserve deterministic and security invariants

When changing the runtime, protect:
- one semantic command per write;
- exact expected revision;
- closed payload contracts;
- server-owned chronology and contested outcomes;
- player authority and agency validation;
- ownership and conservation;
- WAL/receipt idempotency;
- exact preview attestation for new writes;
- no stochastic or hidden-future preview probing;
- fail-closed remote durability;
- bounded player-visible reads with exact rehydration or pagination rather than silent cardinality ceilings;
- knowledge separation;
- repaired transaction tombstones and permanently reserved invalidated request IDs;
- high-salience wake boundaries before autonomous resolution crosses protected player decisions;
- bounded non-authoritative projections/operational memory that never replace exact campaign owners.

Do not weaken an invariant merely to make an integration test easier.

## Player interaction surfaces

Player-authored social, court, petition, audience, or institutional interaction must distinguish **attempt** from **world response**.

- Player input may persist Tang Wei's exact declared target, action, statement, posture, and controlled accompanying formations.
- Player input may not supply NPC reaction, access, acceptance, appointment, rank, vacancy, permission, or other external outcome.
- New player-facing raw `scene_consequence` writes are forbidden. It remains an internal/replay compatibility reducer only.
- The stable surface exposes typed `interaction_action` attempts and translates them before the legacy reducer.
- Waiting is chronology and must use `advance_time`; an interaction attempt by itself does not manufacture elapsed time or a reply.
- A stale authored scene may be replaced only by a revision-matched player-visible runtime projection reconstructed from exact current owners, already-triggered event facts, and typed player attempts. Old prose is continuity only.

## Minimum-sufficient read surfaces

Ordinary `get_play_context` must remain bounded. A truncated hot window is not proof that omitted state does not exist.

Use continuation/read surfaces instead of broadening every turn:
- `get_command_contract` for one advertised semantic command;
- `list_controlled_formations` for controlled-formation pagination;
- `list_known_information` for saved player-known claims outside the hot window;
- `list_interaction_handles` for already-triggered player-visible interaction/message handles;
- `inspect_game_object` for exact rehydration when the supplied ref is lawfully revalidated.

Never solve scale with a silent first/last-N lifetime limit.

## Testing strategy

Normal development verification is:

```text
python tools/quick_check.py
python tools/test_changed.py <changed paths>
```

`quick_check.py` is the fast structural/syntax/production-audit gate. `test_changed.py` routes changed paths to the maintained focused regression slice. Keep these commands fast enough for ordinary implementation work.

Run a deeper individual replay, soak, transaction-recovery, or full Gold diagnostic only when the changed subsystem warrants it. Mutating tests, acceptance scenarios, replay, migration rehearsals, and destructive diagnostics run only on disposable campaign copies.

A test that was not run is neither passing nor failing. CI prevented from starting by billing, runner, quota, or other infrastructure is an infrastructure failure, not source-test evidence.

## Regression design

Prefer state-independent unit/regression fixtures for invariant logic. Keep current-campaign integration tests separately when the evolving snapshot itself is what must be tested.

For changes that alter autonomous scheduling, progression, formations, House or institution settlement, social propagation, economy, family, or another cross-system causal path, synthetic fixtures are not sufficient by themselves. Use deterministic replay on independent disposable copies of the current real campaign snapshot for a meaningful horizon when that subsystem requires it.

## Schema and reducer parity

When a reducer starts writing a new persistent structure, register and test the structure in the canonical schema/template authority in the same change whenever practical. Do not rely on permissive fields as a permanent substitute for mechanically meaningful structure.

## Skill changes

When this Skill changes:
1. update the repository Skill source;
2. keep `SKILL.md` compact and move specialized detail into references;
3. ensure every referenced file exists;
4. package the complete Skill directory as `skill.zip`, not only `SKILL.md`;
5. run Skill validation;
6. use a supported direct Skill update mechanism when available, otherwise give the player the package;
7. verify the installed Skill is actually synchronized before claiming it contains the change.

A GitHub commit updates canonical Skill source, not automatically the ChatGPT-installed copy.

## Deployment changes

Production Railway uses a persistent campaign checkout and a separate runtime root. Verify:
- runtime, game, dependency, or deployment changes trigger deployment;
- gameplay `state/**`, Skill, docs, tests, tools, workflow-only, and README changes do not create deployment loops;
- `/health` remains available;
- bootstrap handles fast-forward, local-ahead recovery, dirty checkout, and safe history replacement correctly;
- production uses one runtime instance;
- remote Git durability remains inside the transaction coordinator.

For OAuth/MCP, verify protected-resource metadata, issuer/audience/JWKS, scopes, subject allowlist, tool discovery, exact preview/execute, and that no secret is printed or committed.

A server deployment is not proof that ChatGPT has refreshed its MCP action schema. If tool definitions change, verify the connected app exposes the new tool list. If it does not, the custom app/action snapshot must be refreshed or republished before live play can use the new tools.

## Git discipline

Preserve Git history as development and campaign provenance.

Default small requested implementation work to direct `main` commits. Use an isolated branch for broad/risky work, explicit review, repository policy, blocked direct writes, or temporary release isolation. Before moving `main` from an isolated branch, re-read current `main`; if it advanced independently, integrate deliberately rather than force-resetting it.

Never force-push campaign history as a routine release strategy.

## Completion gate

Do not call OOC DEV work complete until the relevant parts are done:
- source implementation committed;
- references/docs aligned;
- quick plus focused verification run when the environment permits;
- deeper diagnostics run when required by the changed subsystem;
- Skill packaged and validated if modified;
- deployment configuration prepared;
- remaining user-only secret/UI steps stated explicitly;
- live integration test plan defined when deployment is involved.

If an external UI or credential is required and cannot be operated by the available tools, stop at the exact user action required rather than pretending deployment is complete.
