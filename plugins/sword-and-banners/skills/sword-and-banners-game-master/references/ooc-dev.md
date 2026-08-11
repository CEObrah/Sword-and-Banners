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

Do not design from stale chat memory when GitHub can answer the question.

## Separate code, game data, and campaign repair

Classify each proposed change:

**Runtime/source change**: executable behavior, API, transactions, scheduler, combat, warfare, validation, autonomy.

**Game/rule/data change**: static mechanics, schemas, world content, economy, locations, doctrine, historical background.

**Skill/presentation change**: GM procedure, narration, player UX, choice framing.

**Campaign truth repair**: correcting a committed state fact that is actually wrong.

Never hide a campaign repair inside a source refactor. Never patch `state/` casually because a test or narrative feels inconvenient.

Confirmed bad campaign state should use an explicit repair or migration mechanism with provenance, validation, and a narrow scope.

## Preserve deterministic and security invariants

When changing the runtime, protect:
- one semantic command per write;
- exact expected revision;
- closed payload contracts;
- server-owned chronology;
- server-owned contested outcomes;
- player authority validation;
- ownership and conservation;
- WAL/receipt idempotency;
- exact preview attestation for new writes;
- no stochastic preview probing;
- fail-closed remote durability;
- bounded player-visible reads;
- knowledge separation;
- state-only commits not causing deployment loops.

Do not weaken an invariant merely to make an integration test easier.

## Testing and release gate

After meaningful runtime/game/service changes, run the repository's Gold production gate rather than a cherry-picked happy-path test.

Gold should verify, as applicable:
- production audit;
- syntax/import health;
- architecture/service behavior;
- transactions and recovery;
- hostile command inputs;
- semantic surface;
- long-horizon behavior;
- warfare and siege rules;
- mandatory soak.

Treat a failing gate as evidence to diagnose, not a nuisance to bypass. If a gate itself is stale, modernize it or maintain deliberate compatibility without changing the production invariant being tested.

## Skill changes

When this Skill changes:
1. update the repository Skill source;
2. keep `SKILL.md` under the recommended size and move specialized detail into references;
3. ensure every referenced file actually exists;
4. package the complete Skill directory, not just `SKILL.md`;
5. run skill validation;
6. give the player the new package so the installed Skill can be replaced.

Do not embed secrets or deployment credentials in Skill files.

## Deployment changes

Production Railway uses a persistent campaign checkout and separate runtime root. Verify:
- source changes trigger deployment;
- state-only gameplay commits do not;
- `/health` remains available;
- bootstrap handles fast-forward, local-ahead recovery, dirty checkout, and safe history replacement correctly;
- production uses one runtime instance;
- remote Git durability is wired inside the transaction coordinator.

For OAuth/MCP, verify:
- protected-resource metadata;
- issuer/audience/JWKS configuration;
- read and write scopes;
- subject allowlist;
- tool discovery;
- exact preview/execute workflow;
- no secret values are printed or committed.

## Git discipline

Preserve Git history as development and campaign provenance.

For broad risky changes, an isolated branch is appropriate until Gold is green. Before moving `main`, re-read the current main head. If main advanced independently, integrate deliberately rather than force-resetting it.

Never force-push campaign history as a routine release strategy.

## Completion gate

Do not call OOC DEV work complete until the relevant parts are done:
- source implementation committed;
- references/docs aligned;
- tests/gates green;
- Skill packaged and validated if modified;
- deployment configuration prepared;
- remaining user-only secret/UI steps stated explicitly;
- live integration test plan defined when deployment is involved.

If an external UI or credential is required and cannot be operated by the available tools, stop at the exact user action required rather than pretending deployment is complete.
