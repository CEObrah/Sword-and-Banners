# GitHub Development

Use this reference only for `OOC DEV:` repository work. GitHub is source/development infrastructure, never the live player-state API or a combat/simulation authority. Normal gameplay does not poll GitHub Actions.

## Choose the right editing surface

Use the GitHub connector for repository inspection, commit archaeology, small coherent patches, branch/PR review, and required-check inspection. Prefer an uploaded or local repository workspace for broad refactors, migrations/repairs, release cleanup, large file replacement, or coupled runtime/schema/data/test changes so the edit can be validated atomically.

Never read GitHub to answer current campaign-state questions. Use the live Sword Runtime for those.

### Live-state hard guard

Never edit `state/` on the live/default branch merely to change prose, labels, aliases, formatting, UI wording, or another presentation-only concern. Presentation belongs in the Skill or another non-authoritative presentation owner. A real campaign-truth correction requires an explicit repair/migration with provenance and validation; an ordinary gameplay change must use the live semantic-command transaction path.

Before any direct GitHub write touching `state/`, state the exact campaign-truth defect being repaired and verify that a presentation, source, rules, or runtime owner cannot solve it instead. If that defect cannot be established, do not write `state/`.

## Classify connector and CI failures before retrying

A failed connector call changed nothing unless its result explicitly proves a write committed.

1. **Stale SHA/ref/divergence or ordinary API validation**: refresh the exact target branch/ref/file, correct the request, and retry normally. Never reuse a blob SHA from another branch or an earlier version.
2. **Permission/authentication/infrastructure failure**: fix the actual permission, connection, quota, runner, or dependency issue. Do not claim the requested write or test occurred.
3. **Tool or platform safety block**: treat it as a hard no-write result. Do not probe around the block. Switch to an authorized local/uploaded workspace when possible, or stop that write and report the limitation.
4. **Required GitHub Action failed**: inspect the failing job/assertion and classify whether the implementation, test expectation, fixture, dependency/environment, or workflow is wrong. Repair the correct owner and push again. Never change a sound game rule merely to make a stale test green.

Do not confuse a safety block, CI failure, or Git conflict with one another.

## Safe branch -> CI -> merge -> Railway workflow

1. Read exact current `main`, then edit the authoritative owner on an isolated branch for nontrivial work.
2. Keep runtime, schemas/contracts, game data, tests, and Skill references aligned in one coherent change.
3. Run local verification on the actual editing workspace:

```text
python tools/quick_check.py
python tools/test_changed.py <changed paths>
```

4. Push the branch/open the PR. The repository `verify` workflow reruns the structural gate and changed-owner regression selection from a clean standard GitHub runner.
5. Inspect required checks. Red means diagnose/fix/push/re-run. Green means the clean checkout passed the configured merge gate; it does **not** substitute for local verification.
6. Re-read/compare latest `main`, integrate deliberate concurrent work, and merge only when required checks remain green. For this project, an explicit `OOC DEV:` implementation/fix request includes authority to merge the finished PR automatically once required checks are green and the branch is current, unless the player explicitly says `review only`, `PR only`, `do not merge`, or equivalent. Do not stop to ask for a separate merge confirmation after the requested work is finished. Never force-push campaign history as a routine workaround.
7. Railway may auto-deploy `main`; verify deployed source head and the smallest safe live smoke path before declaring production updated. Deployment, campaign-state durability, MCP schema refresh, and installed GM Skill refresh remain distinct.
8. Return to normal play/playtesting. Any mechanical defect found in play should become a focused regression when practical, then re-enter this loop through explicit `OOC DEV:`.

The hosted workflow is deliberately not a giant soak suite. `quick_check.py` protects syntax/JSON/schema integrity. `test_changed.py` always includes architecture/transaction coverage and routes real changed owners to maintained regressions; a second clean runner executes persistent runtime invariants in isolation because those tests deliberately exercise locking/recovery boundaries. Run `python tools/run_release_suite.py`, deterministic current-campaign replay, or recovery diagnostics when the subsystem/release warrants them rather than making every small PR expensive and noisy. The separate scheduled/manual `soak` workflow runs only the maintained long-horizon vitality, no-global-scan, and named-person identity checks; it is observational CI, not a live-game scheduler.

## Verification states are distinct

Keep these statements separate:
- edited locally;
- local tests executed and passed;
- committed/pushed to Git;
- required GitHub Actions executed and passed;
- merged on GitHub;
- Railway deployed the source revision;
- live smoke check passed;
- ChatGPT refreshed the MCP action schema;
- the installed GM Skill was updated.

One never implies the next.
