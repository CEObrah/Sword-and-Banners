# Campaign Rebaseline - 2026-09-02

This package establishes the repaired current world snapshot as a **new revision-1 campaign baseline**. The old revision-51 state is retained only as forensic evidence in `docs/forensics/campaign-state-revision-51-pre-rebaseline.tar.gz`.

## What was preserved

All current authoritative hard world state, world time, people, formations/forces, economy, injuries, locations, scheduler/frontier state, politics, relationships, knowledge, and other typed owners were preserved. This rebaseline does **not** guess which historical hard consequences were good or bad by reversing them without evidence.

## What was reset

- `state/meta.json` starts at revision **1**.
- Old authority-false scene/session/interaction residue was cleared so development-era dialogue and stale scene continuity do not seed the new narrative.
- Development repair provenance that was not active campaign truth was moved outside active authority where applicable.
- No prior WAL, idempotency receipt, lock state, or private recovery artifact may be reused with this baseline.

## Canonical Git topology

The game uses **one branch only: `main`**. Source code, static data, Skill source, and committed campaign-state transactions all live on that branch. Runtime-generated state-only commits do not trigger Railway rebuilds because `railway.toml` excludes `state/**` from deployment watch paths. No campaign durability branch is required.

## Deployment requirement

1. Commit this complete revision-1 package to `main`.
2. Delete/ignore any old campaign branches if desired; the pre-rebaseline state is already preserved under `docs/forensics/`.
3. Clear the old Railway persistent campaign checkout/volume.
4. Clear the old private runtime recovery/WAL/receipt store.
5. Deploy from `main`. The shipped start command pins `SWORD_GIT_BRANCH=main` and runs the ordinary fail-closed `sword_runtime.bootstrap`.
6. Confirm the live runtime reports revision **1** before consequential play.

Do not point revision 1 at an old revision-51 checkout or old receipt store. The runtime intentionally refuses unsafe rollback/divergence states.

## Why this is safe

Revision numbers are concurrency/idempotency state, not story prestige. This is an explicit new campaign baseline on a clean runtime lineage, not an in-place rewind. The archived pre-rebaseline state remains available for bug forensics and regression fixture extraction while no longer acting as campaign authority.
