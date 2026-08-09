# Player Interface

This file defines optional control grammar for ChatGPT. It is interface documentation, never fictional campaign state.

## Intent boundary

- `OOC:` discussion/design only. Never persist a roster, appointment, relationship, acquisition, war plan, doctrine change, or other campaign fact.
- Ordinary in-world natural-language declarations are gameplay instructions. Validate authority, resources, time, information, legality, and persistence before narrating success.
- Questions, comparisons, audits, hypotheticals, wishlists, and brainstorming are nonpersistent unless the player actually forms or communicates the intent in-world.

No special gameplay command prefix is required.

## Project/runtime controls

`CONTINUE GAME`, `ADVANCE TIME <target>`, `RESUME HORIZON`, `CHECKPOINT`, and `AUDIT` are project controls, not in-world standing orders. CHECKPOINT advances no future time. Generated status cards, decision matrices, age displays, authority views, training summaries, and arc summaries are derived views and own no durable facts.

## Military and personal-force management

Recognize structured natural-language commands: `FORM UNIT`, `SPLIT UNIT`, `MERGE UNIT`, `REFIT UNIT`, `FORM FORMATION`, `FORMATION SETUP`, `SET COMMAND`, `DELEGATE COMMAND`, `SHOW COMMAND CAPACITY`, `SET DOCTRINE`, `SET TENDENCIES`, `SET LOADOUT`, `SET TRAINING`, `SET STANDING ORDERS`, `ATTACH UNIT`, `DETACH UNIT`, `SHOW UNIT`, `SHOW FORMATION`, `SHOW COMMAND`, and `REORGANIZATION REVIEW`.

A unit is persistent. A formation groups units for an operation. A command assignment changes authority, never ownership. State-issued or institution-issued troops retain source ownership, source representation, equipment ownership, and return conditions unless a separate lawful transfer occurs.

### Setup fields

Target/source; ownership; permanent yes/no; name; role; commander; deputy; succession; members/source manpower; doctrine; tendencies; loadout; training; communications; contingencies; standing orders; home; assignment; march order; battle deployment; scouting; reserve; logistics; withdrawal; pursuit.

Before persistence, resolve authority, manpower, horses, equipment, instructors, facilities, training time, operating burden, supply, command familiarity, and blockers.

## Structured setup blocks

### Personal-force unit

```text
FORM UNIT
Source: Tang Wei Personal Retinue or another lawfully owned personal force
Ownership: retain current personal-force owner
Permanent: yes
Name:
Role:
Members/source manpower:
Commander:
Deputy:
Succession:
DOCTRINE:
COMBAT TENDENCIES:
LOADOUT STANDARD:
TRAINING PLAN:
STANDING ORDERS:
HOME:
NORMAL ASSIGNMENT:
```

### Operational formation from assigned troops

```text
FORMATION SETUP
Source: forces currently assigned to command
Ownership: retain every source unit's original ownership
Name:
Purpose:
Commander:
Deputy:
Included units:
Commander interpretation:
Temporary battle orders:
March order:
Scouting:
Reserve:
Flanks:
Logistics:
Supply:
Withdrawal:
Pursuit:
```

Never absorb assigned troops into Tang Wei's personal force unless a separate lawful transfer explicitly changes ownership.

`SHOW UNIT`, `SHOW FORMATION`, and `SHOW COMMAND` are read-only. `SET DOCTRINE`, `SET TENDENCIES`, `SET LOADOUT`, `SET TRAINING`, and `SET STANDING ORDERS` modify only the named layer and do not silently rewrite the others.


## Split, merge, refit, and delegation

- `SPLIT UNIT <unit> INTO ...` partitions one homogeneous unit. Neutral splits preserve the parent represented capability distribution and allocate integer categories deterministically. Selecting veterans/specialists is a separate evidence/time-consuming selection action.
- `MERGE UNIT <units>` merges compatible same-troop-type units after standards/authority are reconciled. Capability moments pool by personnel; cohesion may fall from integration.
- `REFIT UNIT <unit> TO <loadout>` changes the target standard for the entire unit. If only a subset should change, split first. Refit requires actual equipment, custody/transport, fitting/maintenance, ammunition or mounts where relevant, familiarization and elapsed time.
- `DELEGATE COMMAND <units> TO <commander>` creates/updates a subordinate command node. Whole delegated units stop counting against the superior direct-personnel/leaf-unit load and instead consume one subordinate-command slot in the superior.
- `SHOW COMMAND CAPACITY <commander>` reports base rating, evidence-supported capacity modifiers, effective direct-personnel capacity, effective direct-command-slot capacity, current direct load, strategic recursive total, load ratios, band, and which branches should be delegated if overloaded.

Personal, assigned, attached, institutional, allied-under-command and hired troops use **one shared command budget** when they report directly. Ownership never creates a second free capacity ledger. A direct leaf unit costs one slot; a subordinate command node also costs one slot.

## Attachment and return

`SHOW HOME <unit/person>` shows source owner, home unit, current parent, current commander, and return policy.

`ATTACH UNIT` changes operational command only.

`RETURN UNIT` / `RETURN DETACHMENT` ends temporary assignment, dissolves receiving-only formations, restores the source home chain, reconciles equipment/horse custody, and triggers source-owner reconstitution. It never regenerates losses.

World-owned armies, mercenary companies, escort bureaus, martial schools, House forces, and other organized combat bodies already possess home units, doctrine/training/loadout standards, tendencies, standing procedures, and formation templates. Tang Wei's personal retinue and raw personnel explicitly given to him to organize remain player-designed.

## Homogeneous unit rule

A unit contains exactly one troop type. Never mix infantry and archers, infantry and cavalry, medical and logistics, or other materially different troop types into one unit.

Example: Qin assigns Tang Wei **5,000 infantry and 2,000 archers**. He may keep them as two units, or split them. If he halves both troop types, the result is **four units**: 2,500 infantry, 2,500 infantry, 1,000 archers, and 1,000 archers. He may assign one infantry unit and one archer unit to the same commander, but they remain separate unit owners with separate doctrine, loadout, condition, cohesion, and combat resolution.

Tang Wei's 50 individually represented Household Champions can likewise become two 25-person units with separate commanders/doctrines while all 50 named individual-lite people remain persistent. `permanent_units: []` means the personal force currently has people but Tang Wei has not yet created any persistent units.

Raw unorganized manpower may exist temporarily as a troop pool/allocation for accounting, but a troop pool never fights directly. Allocate it into homogeneous units before deployment.

## Reputation and recognition

`SHOW REPUTATION <subject> [audience]` is read-only. It shows only reputation state the player can lawfully know; hidden audience beliefs remain hidden unless intelligence/reporting reveals them.

`SHOW RENOWN <subject>` summarizes player-known professional/public recognition without inventing a universal fame score. `SHOW PRESTIGE <subject> [audience]` and `SHOW NOTORIETY <subject> [audience]` follow the same knowledge gate.

There is no `SET REPUTATION` command. Reputation changes only through causal events, witnesses, reports, propaganda/counter-propaganda, appointments/honors, contracts, battles, scandals, and other world actions resolved by the reputation mechanics. `OOC:` may estimate possible audiences/risks but changes nothing.

### Command-tree display

`SHOW COMMAND TREE <commander>` is read-only. Display direct troop units and subordinate command groups at the same indentation level. A subordinate command group is labeled `<Commander> Command` (or its saved display name) and expands to its own direct units/nodes beneath it. It counts as one direct command slot in the parent, but it is **not** a troop unit and owns no manpower.

Example:
```text
Wei
├── Archer Unit
├── Infantry Unit
├── Mercenary Unit
└── Jang Command
    ├── Infantry Unit II
    ├── Spear Unit
    └── Archer Unit II
```

The commander named on a command group remains an independently simulated person in combat. If Jang is wounded/killed/captured/cut off, resolve succession and communication; do not delete or regenerate Jang's subordinate units.

## Family and succession controls

Natural language remains primary. Structured aliases are optional:

- `SHOW FAMILY <person>` — read-only unions, household/dependent/parentage/succession refs known to the player.
- `SHOW SUCCESSION <House/clan/title>` — read-only current succession state/known claims.
- `OOC: MARRIAGE <person>` — OOC/read-only implications, blockers and likely required authorities; creates no intent.
- ` PROPOSE MARRIAGE TO <person>` — explicit in-world proposal attempt; does not force acceptance.
- ` ACCEPT PROPOSAL <id>` / ` DECLINE PROPOSAL <id>` — explicit player response after loading the real pending proposal.
- ` END/RENEGOTIATE BETROTHAL <id>` and family/household orders use the same authority/time/persistence contract.

A proposal *to* the player can exist as world state without becoming player intent. OOC discussion never creates courtship, betrothal, marriage, parenthood, adoption or divorce state.
