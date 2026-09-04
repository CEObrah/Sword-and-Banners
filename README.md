# Sword & Banners

Persistent deterministic Warring States RPG operated through ChatGPT and the Sword runtime.

## Authority

- `runtime/`: deterministic engine, transactions, scheduling, exact combat, warfare, economy and simulation.
- `game/`: current mechanics, schemas, rules and world data.
- `state/`: minimum sufficient current campaign truth.
- `plugins/sword-and-banners/skill/sword-and-banners-game-master/`: ChatGPT GM procedure and presentation.
- `tests/`: current behavior verification.

Development history is not campaign state. This package is an explicit **revision-1 rebaseline** of the repaired current world snapshot. The pre-rebaseline revision-51 state is preserved only under `docs/forensics/` for failure analysis. Gameplay idempotency receipts and WAL state are runtime-private and must begin fresh for this baseline.


## AI-native scene direction

The deterministic runtime owns world truth, physical/mechanical consequences, chronology, knowledge boundaries, conservation, and persistence. ChatGPT owns scene direction and prose. The live `gm_scene_context.scene_direction` packet is a compact, non-authoritative handoff that identifies current actors, open human/practical threads, recent causal material, and protected player decisions; the repository Game Master Skill supplies the detailed directing doctrine.

Present NPCs are active agents rather than response functions. The LLM may stage grounded reversible dialogue, interruption, cross-talk, practical activity, humor, refusal, silence, and incidental behavior without waiting for a Python dialogue script or player activation. A shown scene must normally advance through a new human/practical/causal beat or compress/transition; paraphrase-only turns and stock nod/pause/gaze filler are explicitly invalid presentation. Scene completion is equally important: once current pressure is spent, the LLM transitions instead of keeping the same tableau alive. Contested physical outcomes remain runtime-owned.


Formal scene sessions are continuity tools, not story locks. The LLM decides narrative scene start/continue/transition/end from lived pressure. Fresh physical projection removes departed people from live dialogue eligibility while retaining them only as explicit continuity-only absent participants when needed for cleanup/resumption; an unanswered thread never makes an absent NPC speak. Active-session actors and people tied to the current event/process are prioritized ahead of general site attendance, while hard movement, time, combat, money, authority, injury, and other durable consequences remain runtime-owned.

## Current campaign baseline

- Campaign revision: **1** (new canonical baseline; pre-rebaseline revision 51 is forensic only).
- Campaign: `sword-banner-tang-wei-main`.
- Canonical world time: `244-BCE-10-04T06:00:00+08:00`.
- Player: Tang Wei.
- Git topology: source and gameplay durability both use the single canonical branch `main`; no separate campaign branch is required.
- This package contains the current source plus canonical baseline state. Commit it to `main`, then deploy only after the old Railway campaign checkout and private recovery/WAL/receipt store have been cleared.

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

Pull requests and pushes to `main` also run `.github/workflows/verify.yml` on a clean standard GitHub runner. The hosted gate reruns the maintained fast syntax/JSON/schema check and repository-defined focused invariants. Long-horizon/replay work remains deliberate release QA through the repository's maintained test and release tools rather than a second campaign authority. Local verification, GitHub CI/merge, Railway deployment, live smoke/playtesting, MCP schema refresh and installed Skill state are separate tiers.
