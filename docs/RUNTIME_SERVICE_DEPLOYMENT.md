# Sword & Banners runtime deployment

## Topology

```text
ChatGPT -> Sword & Banners GM Skill -> authenticated MCP -> Railway runtime
                                                     -> persistent Git checkout on main
                                                     -> private WAL/locks/receipts
                                                     -> Git remote main
```

Use a single mutable campaign writer. Keep private recovery data outside the Git checkout.

## Railway environment

```text
SWORD_CAMPAIGN_ROOT=/data/campaign
SWORD_RUNTIME_ROOT=/data/runtime
SWORD_GIT_URL=https://github.com/CEObrah/Sword-and-Banners.git
SWORD_GIT_REMOTE=origin
SWORD_GIT_BRANCH=main
RAILPACK_DEPLOY_APT_PACKAGES=git
```

Set `SWORD_GIT_TOKEN` privately in Railway with only the repository access needed for runtime fetch/push durability. Never commit it.

The production start command is:

```text
SWORD_GIT_BRANCH=main PYTHONPATH=/app/runtime python -m sword_runtime.bootstrap
```

Health endpoint: `/health`.

## Single-main source and campaign durability

`main` is the only required Git branch. Source releases and runtime-generated campaign transactions share that branch. `railway.toml` excludes `state/**` from deployment watch paths, so state-only gameplay commits do not rebuild the service.

Remote transaction preflight requires exact synchronization against fetched `main`. A source release racing a gameplay write causes the gameplay write to fail closed instead of overwriting the source head. Startup safely fast-forwards a clean checkout, preserves only provable WAL-owned crash evidence, and rejects unexplained divergence.

## Revision-1 rebaseline deployment

Commit this complete revision-1 package to `main`, then clear both the old persistent campaign checkout and the old private runtime WAL/receipt directory before deploying. The fresh Railway checkout clones revision 1 directly from `main`. No runtime branch migration or history rewind is required.

The pre-rebaseline revision-51 state is preserved under `docs/forensics/`; legacy campaign branches are not needed and may be deleted.

## Deployment verification

Git commit, Railway deployment, campaign-state durability, MCP schema refresh, and installed Skill refresh are separate tiers. After deployment, confirm `/health`, bounded OOC audit, and `get_play_context` all resolve against revision 1 before consequential play.

## Transactions and recovery

Persistent writes retain exact expected revision, preview attestation, one semantic command per transaction, atomic staged writes, conservation checks, Git durability, WAL/receipt idempotency, and fail-closed retry/recovery. Never reuse the old revision-51 recovery store with the revision-1 baseline.
