# GitHub Connector Development

Use this reference for OOC DEV repository work when the connected GitHub surface is available, especially when a private local clone is unavailable or unauthenticated.

## Treat GitHub as a first-class development surface

Do not stop merely because the local execution environment cannot clone the private repository. If the GitHub connector has the required read/write permission, use it directly while preserving the same source-control discipline as local Git.

Preferred workflow:
1. read repository metadata and the exact current `main` ref;
2. read the exact target branch ref and recent relevant commits;
3. fetch only the authoritative owner files needed for the change;
4. for broad or risky work, create/use an isolated branch from the verified current base;
5. before replacing an existing file, fetch that file from the **target branch** and use its returned blob SHA, not a SHA remembered from `main` or an earlier read;
6. write the smallest coherent files and keep schema/contracts/tests/docs aligned;
7. compare the development branch against the latest `main` before merge;
8. inspect commit status/workflow runs when CI is available;
9. re-read `main` before merge and integrate deliberately if it advanced;
10. merge or fast-forward without force-pushing campaign history.

A connector write rejected by permission, safety, stale SHA, or another API error made no source change unless the returned result explicitly proves otherwise. Never report a blocked write as committed.

## Verification without a local clone

The preferred source verification remains:

```text
python tools/quick_check.py
python tools/test_changed.py <changed paths>
```

When the execution environment cannot obtain the private repository, do not claim those commands ran. Use repository CI/status checks if they actually execute the maintained gates. If Actions cannot start because of billing, quota, runner, or permission infrastructure, report that as unrun verification rather than a source-test failure or success.

Connector-level review should still include:
- exact branch-vs-main diff/changed-file inspection;
- schema/reducer parity review for every new persistent write shape;
- focused regression source inspection;
- deployment-watch impact;
- Skill packaging/validation separately when Skill source changed.

Source-complete, test-verified, merged, deployed, and live-integrated are different completion states. State each accurately.

## Avoid stale-SHA and broad-read mistakes

The contents API requires the blob SHA of the version being replaced on the target branch. Fetch it immediately before the write when the branch has changed. A SHA from another ref may produce a conflict even when the text looks identical.

Prefer exact file reads and bounded line ranges over broad repository dumps. Use repository maps and current owner files to route changes rather than searching every directory.
