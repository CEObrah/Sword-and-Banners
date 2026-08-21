# Sword & Banners

Persistent deterministic Warring States RPG operated through ChatGPT and the Sword runtime.

## Authority

- `runtime/`: deterministic engine, transactions, scheduling, exact combat, warfare, economy and simulation.
- `game/`: current mechanics, schemas, rules and world data.
- `state/`: minimum sufficient current campaign truth.
- `plugins/sword-and-banners/skills/sword-and-banners-game-master/`: ChatGPT GM procedure and presentation.
- `tests/`: current behavior verification.

Development history is not campaign state. The current save starts at revision 1 and contains only current campaign truth. Gameplay idempotency receipts are runtime-private and begin fresh when a new runtime volume starts from this save.

## Current combat and mount model

- Personal combat is continuous N-actor action-ready time, not alternating turns.
- Permanent anatomy loss persists and affects the specific bodily functions it physically constrains without deleting learned skill.
- One canonical `horse` type is used for mounted troops and chariots.
- Direct riders consume one horse each.
- Each operational chariot consumes three remaining horses plus one physical chariot platform and its crew.
- Exact personal-combat mounts can be wounded, disabled or killed. A mount casualty unhorses the rider on the shared clock and cannot be resurrected by a static role loadout.
- Formation-scale horse casualties and exact-person mount casualties are conserved against the owning horse authority.
- Command ownership and operational nesting are separate: any lawful army/force can serve as an intact nested command under a larger initiative while retaining its own commander, ownership, manpower, equipment and internal hierarchy.
- Exact civilian/independent military aspirants enter service by reclassifying one conserved population body; combat recruits receive physical posting orders rather than free command, and staff candidates receive no automatic office.
- Exact civilian population owners settle births and ordinary civilian deaths explicitly on their demographic clock; population growth is the resulting balance, not a flat multiplier.

## Verification

```bash
python tools/quick_check.py
python tools/test_changed.py
python tools/run_release_suite.py
```

Deployment, Railway volume reset, Git push, MCP schema refresh and installed Skill state are separate tiers.
