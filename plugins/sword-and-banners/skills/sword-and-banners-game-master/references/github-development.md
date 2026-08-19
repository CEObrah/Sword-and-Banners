# GitHub Development

Use this reference only for `OOC DEV:` repository work. GitHub is source/development infrastructure, never the live player-state API.

## Choose the right editing surface

Use the GitHub connector for repository inspection, commit archaeology, small coherent patches, and branch/PR review. Do not make GitHub Actions or hosted CI a release dependency; verification authority is the local repository test suite.

Prefer an uploaded or local repository workspace when one is available for broad refactors, migrations/repairs, release cleanup, large file replacement, or changes spanning many coupled schemas/runtime/state/tests. Local work is easier to validate atomically and avoids turning connector limitations into architecture decisions.

Never read GitHub to answer current campaign-state questions. Use the live Sword Runtime for those.

### Live-state hard guard

Never edit `state/` on the live/default branch merely to change prose, labels, aliases, formatting, UI wording, or another presentation-only concern. Presentation belongs in the Skill or another non-authoritative presentation owner. A real campaign-truth correction requires an explicit repair/migration with provenance and validation; an ordinary gameplay change must use the live semantic-command transaction path.

Before any direct GitHub write touching `state/`, state the exact campaign-truth defect being repaired and verify that a presentation, source, rules, or runtime owner cannot solve it instead. If that defect cannot be established, do not write `state/`.

## Classify connector failures before retrying

A failed connector call changed nothing unless its result explicitly proves a write committed.

1. **Stale SHA/ref/divergence or ordinary API validation**: refresh the exact target branch/ref/file, correct the request, and retry normally. Never reuse a blob SHA from another branch or an earlier version.
2. **Permission/authentication/infrastructure failure**: fix the actual permission, connection, quota, runner, or dependency issue. Do not claim the requested write or test occurred.
3. **Tool or platform safety block**: treat it as a hard no-write result. Do not repeatedly rephrase, split, probe, or use lower-level Git calls to bypass the block. Switch to an authorized local/uploaded workspace when possible, or stop that write and report the limitation.

Do not confuse a safety block with a Git conflict. Do not use accidental probe commits to discover connector behavior.

## Safe GitHub workflow

1. Read repository metadata and exact current `main`.
2. Read the target branch and only the authoritative owner files needed.
3. For broad/risky work, use an isolated branch.
4. Fetch the exact target-branch file immediately before replacement and use that version's SHA.
5. Keep runtime, schemas/contracts, tests, data, and Skill references aligned in the same coherent change.
6. Compare the development branch with the latest `main` before integration.
7. Run the local structural and changed-path gates on the actual editing workspace; hosted CI is optional evidence only and never required release authority.
8. Re-read `main` before merge; integrate deliberate concurrent changes rather than force-resetting them.
9. A normal PR merge is a valid fallback when direct ref movement is unavailable. Never force-push campaign history as a routine workaround.

## Verification states are distinct

Keep these statements separate:
- edited locally;
- committed to Git;
- pushed/merged on GitHub;
- tests executed and passed;
- Railway deployed the source;
- ChatGPT refreshed the MCP action schema;
- the installed GM Skill was updated.

One never implies the next.

Preferred local verification:

```text
python tools/quick_check.py
python tools/test_changed.py <changed paths>
```

Use `python tools/run_release_suite.py` for deliberate release verification, not every small patch.
