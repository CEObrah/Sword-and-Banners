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

Do not design from stale chat memory when GitHub can answer the question. When a sister game such as Shinobi has already encountered the same architectural or live-play failure class, inspect the current source/commit that fixed it and port the reusable invariant rather than rediscovering the defect. Do not copy genre-specific mechanics blindly.

## Separate code, game data, and campaign repair

Classify each proposed change:

**Runtime/source change**: executable behavior, API, transactions, scheduler, combat, warfare, validation, autonomy.

**Game/rule/data change**: static mechanics, schemas, world content, economy, locations, doctrine, historical background.

**Skill/presentation change**: GM procedure, narration, player UX, choice framing.

**Campaign truth repair**: correcting a committed state fact that is actually wrong.

Never hide a campaign repair inside a source refactor. Never patch `state/` casually because a test or narrative feels inconvenient.

Confirmed bad campaign state should use an explicit repair or migration mechanism with provenance, validation, and a narrow scope.

If a deliberate repair restores campaign state to a revision earlier than an already-issued runtime receipt, register that exact removed transaction in `runtime/contracts/transaction-invalidations.json`. The tombstone must bind campaign ID, request ID/digest, transaction ID, removed committed revision, restored revision, bad commit, repair commit, and reason. Never delete or reuse the old request ID. Production recovery fails closed on unexplained future receipts.

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
- state-only commits not causing deployment loops;
- repaired transaction tombstones and permanent invalidated-request reservation;
- high-salience wake boundaries before autonomous resolution crosses protected player decisions;
- bounded non-authoritative operational memory that never replaces exact campaign owners.

Do not weaken an invariant merely to make an integration test easier.

## Testing and release gate

After meaningful runtime/game/service changes, run the repository's Gold production gate rather than a cherry-picked happy-path test.

Gold should verify, as applicable:
- production audit;
- syntax/import health;
- architecture/service behavior;
- transactions and recovery;
- repair/receipt integrity;
- hostile command inputs;
- semantic surface;
- long-horizon behavior;
- warfare and siege rules;
- living-world intelligence and wake boundaries;
- mandatory soak.

Treat a failing gate as evidence to diagnose, not a nuisance to bypass. If a gate itself is stale, modernize it rather than preserving obsolete duplicate documentation or deployment authorities merely to satisfy a path assertion.

Run mutating tests, acceptance scenarios, soak tests, migration rehearsals, and destructive diagnostics only on disposable repository/campaign copies. Never point them at the authoritative live campaign root. Tests against an evolving real-campaign snapshot should derive mutable facts from that snapshot rather than hard-coding one revision, timestamp, readiness value, roster, or other naturally changing fact unless that value is an intentional immutable campaign premise.

For changes that alter autonomous scheduling, progression, formations, House or institution settlement, social propagation, economy, family, or another cross-system causal path, synthetic fixtures are not sufficient by themselves. Add or run a deterministic replay on at least two independent disposable copies of the current real campaign snapshot for a meaningful horizon. Require exact equality of the resulting authoritative state, equal revision/time advancement, no unexplained cursor jumps, no unowned terminal consequences, and no mutation of the source campaign. Use a longer replay when the changed hosts wake less frequently than the default horizon.

A CI failure caused by runner infrastructure, billing, quota, or another condition that prevents tests from starting is not a passing gate and is not evidence that source failed. Diagnose it separately, preserve the exact candidate head, and do not promote that head as Gold until the required suite actually runs successfully.

## Skill changes

When this Skill changes:
1. update the repository Skill source;
2. keep `SKILL.md` under the recommended size and move specialized detail into references;
3. ensure every referenced file actually exists;
4. package the complete Skill directory, not just `SKILL.md`;
5. run skill validation;
6. when the current environment exposes a supported direct Skill update mechanism, prefer it to a manual download/re-upload workflow; otherwise give the player the new package;
7. verify the installed Skill is actually synchronized before claiming that it contains the change.

A GitHub commit updates the canonical Skill source, not automatically the ChatGPT-installed copy. Never claim installation success without verification. Do not embed secrets or deployment credentials in Skill files.

## Deployment changes

Production Railway uses a persistent campaign checkout and separate runtime root. Verify:
- source changes trigger deployment;
- state-only gameplay commits do not;
- `/health` remains available;
- bootstrap handles fast-forward, local-ahead recovery, dirty checkout, and safe history replacement correctly;
- production uses one runtime instance;
- remote Git durability is wired inside the transaction coordinator.

Canonical production deployment procedure lives at `docs/RUNTIME_SERVICE_DEPLOYMENT.md`. Do not recreate a second root deployment manual.

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

Default requested implementation work in this repository to direct commits on `main`. Use an isolated branch when the change is broad/risky, the player explicitly requests review, repository policy requires it, direct writes are blocked, or temporary isolation materially reduces release risk. Before moving `main` from an isolated branch, re-read the current main head. If main advanced independently, integrate deliberately rather than force-resetting it.

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
