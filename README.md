# Sword & Banners

Persistent deterministic Warring States RPG operated through ChatGPT and the Sword runtime.

## Authority

- `runtime/`: deterministic engine, transactions, scheduling, exact combat, warfare, economy and simulation.
- `game/`: current mechanics, schemas, rules and world data.
- `state/`: minimum sufficient current campaign truth.
- `plugins/sword-and-banners/skill/sword-and-banners-game-master/`: ChatGPT GM procedure and presentation.
- `tests/`: current behavior verification.

Development history is not campaign state. The current save contains only current campaign truth; its revision advances normally with committed play. Gameplay idempotency receipts are runtime-private and begin fresh when a new runtime volume starts from this save.

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
- Field formations do not own ration or fodder inventories. Strategic supply is derived from current territory, route access, force size, mounts, civilian food stress, and operational separation; fortified-site siege stores remain exact physical stock.
- Persistent operational battles resolve as bounded contact periods across real campaign time. Redeployment and relevant autonomy boundaries can intervene between contacts; dusk defaults to field-camp/security posture, dawn refits only formations that actually camped and only from conserved stock, and explicit night attacks remain possible under saved aggressive orders.
- Battlefield resupply is a delegated 100-person command-echelon task. Missile ammunition is finite, forward carriers can replenish a stable line from real HQ stock, and full-hundred rotations can rest/refit/remount only from material already in formation custody.
- `runtime/sword_runtime/time_integration.py` is the hosted chronology/orchestration authority; domain modules retain their own settlement mechanics rather than duplicating a second scheduler.

## Verification

```bash
python tools/quick_check.py
python tools/test_changed.py <changed paths>
# Deliberate full-release/systemic verification:
python tools/run_release_suite.py
```

Pull requests and pushes to `main` also run `.github/workflows/verify.yml` on a clean standard GitHub runner. The hosted gate reruns the fast syntax/JSON/schema check, changed-owner regressions, cohort-battle integration, and isolated persistent-runtime invariants. `.github/workflows/soak.yml` is scheduled/manual and runs only the maintained long-horizon causal-vitality, no-global-scan, and named-identity persistence tests, so routine PRs stay fast. Local verification, GitHub CI/merge, Railway deployment, live smoke/playtesting, MCP schema refresh and installed Skill state are separate tiers.


## Final production audit

See `SWORD-AND-BANNERS-FINAL-PRODUCTION-AUDIT-2026-08-24.md` for the current production architecture, feature-status matrix, rebaseline results, validation evidence, and remaining verified limitations.
