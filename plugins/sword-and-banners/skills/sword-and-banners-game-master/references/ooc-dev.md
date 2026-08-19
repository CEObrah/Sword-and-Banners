# OOC Development

Use this reference for source/rules/data/Skill/deployment work, repairs, audits, and releases. OOC development never advances campaign time merely because development occurred.

## Establish current authority

Before changing anything:
1. identify the requested editing surface;
2. inspect the current target source, not a remembered copy;
3. route through `runtime/contracts/repository-map.json` and `references/repository-map.md`;
4. inspect recent relevant source changes when behavior may have moved;
5. preserve strong runtime invariants unless the task explicitly changes them.

## Classify the change

**Runtime/source**: executable behavior, commands, scheduler, transactions, simulation, API/MCP.

**Game/rules/data**: static mechanics, schemas, world content, locations, institutions, economy, doctrine.

**Skill/presentation**: GM operating procedure and player-facing narration/UX.

**Campaign-truth repair**: correcting an already-committed fact that is demonstrably wrong.

Do not conceal a campaign repair inside a refactor. In an established campaign repository, use an explicit narrow repair with provenance and validation. If a repair removes a previously receipted transaction, register that exact transaction in `runtime/contracts/transaction-invalidations.json`; never reuse its request ID.


## Preserve runtime invariants

Protect:
- one semantic command per write;
- exact expected revision;
- closed payload contracts;
- server-owned chronology and contested outcomes;
- player agency and authority validation;
- ownership and conservation;
- WAL/receipt idempotency and fail-closed remote durability;
- exact preview attestation for new writes;
- no preview probing of hidden futures/randomness;
- bounded player-visible reads with exact rehydration or pagination;
- knowledge separation;
- high-salience wake boundaries;
- projections/operational memory never replacing exact owners.

Do not weaken an invariant to make a test pass.

## Player interaction boundary

Player-authored social/court/institutional input records only Wei-owned intent. `interaction_action` may include the lawful target/process, action, player statement, posture, and controlled accompanying formations. It may not contain NPC consent, access, acceptance, appointment, vacancy, rank, or other external outcomes.

Stable operations translate `interaction_action` into an internal attempt record. Raw internal scene consequence records are never a player-facing command. Waiting for an external response uses chronology; an interaction attempt alone does not create elapsed time or a reply.

## Representation and conservation

Preserve the military chain:

```text
population -> force manpower/cohort -> persistent formation -> temporary operation/battle arrangement
```

Large armies, House Tang troops, Sword Manor ranks, and ordinary Tang Champions are aggregate cohorts/formations. Formation assignment does not transfer institutional ownership unless an exact rule says so.

Named important people are exact. A Champion becomes exact only if individual relevance requires materialization, consuming/reclassifying the same conserved body.

Tang Wei's personal force is cohort-first at scale. A direct recruitment campaign accepts conserved bodies into one or more provenance-backed intake cohorts; it does **not** create an individual record for every accepted retainer. Materialize a persistent `person-lite` or exact person only when an existing cohort member becomes named, exceptional, socially important, specialized, command-relevant, or otherwise causally important. Materialization reclassifies that same body and never creates a duplicate.

Population source and recruitment background are separate authorities. The runtime/game data owns occupational/background distributions, screening transforms, training development, and deterministic sampling. ChatGPT may express intents such as recruiting hunters or selecting strongly for archery; it must never invent starting attributes, skill ranges, selection bonuses, or hidden individual values.

## Playability is a correctness concern

A technically valid world can still be unplayable if active pressure never reaches the player. Treat `playability_vitality` diagnostics as first-class evidence. Investigate active arcs with no lawful next work, reports with no delivery path, completed objectives with no handoff, or repeated downtime that produces only maintenance work.

Do not fix story starvation by inventing outcomes. Repair the causal routing, scheduler, opportunity evaluation, or information delivery owner that should produce the next lawful player-facing consequence.

## Testing

Default verification:

```text
python tools/quick_check.py
python tools/test_changed.py <changed paths>
```

`quick_check.py` is the current structural/schema/conservation gate. `test_changed.py` routes changed owners to focused regressions.

Run deeper replay, long-horizon, transaction-recovery, or full release verification only when the changed subsystem warrants it. Run mutating diagnostics only on disposable copies.

Full release verification:

```text
python tools/run_release_suite.py
```

A test that did not run is neither passing nor failing. Run required verification locally on the editing workspace; GitHub Actions/hosted CI is not part of the Sword release gate.

## Skill changes

When this Skill changes:
1. edit the complete repository Skill source;
2. keep `SKILL.md` compact and route details to references;
3. ensure every referenced file exists;
4. validate and package the whole Skill directory as `skill.zip`;
5. distinguish repository source from the installed ChatGPT Skill and verify installation separately.

## Deployment

Railway source deployment, Git-backed campaign state, MCP schema publication, and ChatGPT connector refresh are distinct operations. Verify each layer actually changed before claiming live integration.

Never expose OAuth secrets, preview secrets, Git tokens, or credential-bearing transport errors.

## GitHub connector

When using the connected GitHub development surface, read `references/github-development.md`. For a broad refactor or release consolidation, prefer an authorized uploaded/local workspace when available rather than forcing the connector to act like a bulk filesystem editor.
