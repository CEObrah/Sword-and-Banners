# Final Release Status - 2026-09-02

## Canonical package state

- Campaign revision: **1**.
- Canonical Git branch: **`main` only**.
- Runtime startup: `SWORD_GIT_BRANCH=main PYTHONPATH=/app/runtime python -m sword_runtime.bootstrap`.
- Split campaign/durability branch bootstrap has been removed from the active source tree.
- Pre-rebaseline revision-51 state is preserved at `docs/forensics/campaign-state-revision-51-pre-rebaseline.tar.gz`.
- Deployment requires a fresh/cleared Railway campaign checkout and a fresh/cleared private runtime WAL/receipt/recovery directory.
- No legacy campaign branch is required for recovery or forensics.

## Narrative contract

The repository Skill keeps ChatGPT as the scene engine and the runtime as hard-consequence authority. The long-form scene standard applies to dialogue, family life, travel, training, court/politics, administration, investigation, downtime, personal combat, battles, sieges, aftermath, and transitions. Important sequences should build, develop/reverse, resolve, and leave consequences/residue rather than collapse into command/result/status loops.

Confirmed P0/P1/systemic P2 defects must trigger an audit of the analogous subsystem in the other game before the issue is called globally fixed.

## Verification actually run on this final tree

- `python tools/quick_check.py` - PASS.
- Final main-branch bootstrap/rebaseline/transaction/deployment focused batch - **23 passed**.
- Remaining architecture-service module - **14 passed**.
- Narrative/scene/Skill/cross-game contracts - **84 passed**.
- Battle command/lifecycle/sustainment - **23 passed**.
- Combat cohort/completion - **21 passed**.
- Combat objectives/geometry - **5 passed**.
- Penetration sequencing - **22 passed**.
- Deterministic combat experience - **6 passed**.
- Personal combat action-ready - **3 passed**.
- Multi-actor personal combat - **25/25 passed** in bounded chunks.
- Personal-combat physical rework - **14 passed**.
- Operational battlefield - **11 passed**.
- Warfare/warfare-depth integrity - **8 passed** using the repository-controlled pytest runner.
- Transactions/recovery hardening - **12 passed**.
- Scheduler frontier/host registry - **12 passed**.
- World arcs/player-safe reports/economy feedback - **36 passed**.
- Production/activity living world plus history store - **16 passed**.
- `python tools/validate_release.py` - PASS, **124/124 checks**.

The aggregate `test_changed.py` invocation that selected these systems exceeded the execution window after producing test progress, so it is not claimed as a pass. Its selected release-critical modules were then run directly in smaller repository-controlled batches and passed as listed above.

The package itself still requires deployment-tier verification after the user commits it to `main`, clears the old Railway volumes/recovery store, deploys, refreshes MCP/Skill as needed, and confirms live `get_play_context` reports revision 1.
