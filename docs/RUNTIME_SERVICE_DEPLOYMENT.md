# Sword & Banners runtime deployment

## Topology

```text
ChatGPT -> Sword & Banners GM Skill -> authenticated MCP -> Railway runtime
                                                     -> persistent Git checkout on baseline-scoped campaign branch
                                                     -> private WAL/locks/receipts
                                                     -> Git remote campaign branch + source main
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
PYTHONPATH=/app/runtime python -m sword_runtime.branch_bootstrap
```

`SWORD_GIT_BRANCH=main` remains the **source-branch** environment setting supplied to the process. Do not override the Railway start command with the older direct `sword_runtime.bootstrap` entrypoint. `branch_bootstrap` owns source-release reconciliation, derives or reuses the dedicated campaign durability branch, preserves the original source branch in `SWORD_SOURCE_BRANCH`, then rewrites `SWORD_GIT_BRANCH` internally to the campaign branch before normal bootstrap and startup integrity gates.

Health endpoint: `/health`.

## Ordinary deployment

`main` is the canonical **source** branch. Gameplay durability lives on the dedicated campaign branch derived by `branch_bootstrap`; for certified releases the default ref is `campaign-baselines/<campaign_id>/<release_baseline_id>`. The separate `campaign-baselines/` namespace is deliberate: Git cannot keep a legacy `campaign/<campaign_id>` ref and child refs beneath that same path at once. Scoping by both campaign and certified baseline means an intentional fresh baseline receives a new durability lineage instead of silently reconnecting to an older campaign branch. The persistent checkout is switched to that branch before the runtime starts. `railway.toml` excludes `state/**` from deployment watch paths, so state-only gameplay commits do not rebuild the service.

Normal source deployments **preserve** the existing campaign checkout and private recovery/WAL/receipt directory when the certified `release_baseline_id` is unchanged. Startup fetches `main`, reconciles the exact deployed source revision into that baseline-scoped campaign branch without force-pushing campaign history, preserves only provable WAL-owned crash evidence, and rejects unexplained divergence. If the certified baseline ID changes, bootstrap selects that baseline-scoped durability lineage whether the target branch is newly created or already exists remotely, while leaving the previous campaign branch intact as historical evidence. Recoverable WAL blocks the reset. Once the replacement lineage is selected, completed WAL and idempotency receipts from the retired lineage are moved under `retired-release-baselines/` before new writes can start, so old request IDs cannot answer inside the new baseline. If that retirement fails, bootstrap restores the old checkout and fails closed. Do not clear campaign or recovery volumes merely because ordinary source code changed.

Production deployment attestation must check **both** lineages: `SWORD_SOURCE_BRANCH` must still track the canonical source branch for newer deploy-relevant code, while the rewritten `SWORD_GIT_BRANCH` tracks the campaign durability checkout for state transaction history. Losing the source tracking ref is fail-closed. This prevents a long-lived campaign branch from making an old Railway image appear current merely because only state commits were added to that campaign branch.

Remote transaction preflight requires exact synchronization against the campaign durability branch, while startup/deployment attestation separately proves the immutable image is compatible with the fetched source branch. A source release racing a gameplay write fails closed rather than overwriting either side.

## Current revision authority

Never copy a revision number from README, deployment docs, test names, or a historical audit. `state/meta.json` is the sole mutable authority for the current campaign revision and world time. Verification should assert relationships such as monotonic revision advancement, not a stale hard-coded live value.

The September 2 revision-1 rebaseline is historical lineage only. Its manifest remains in `docs/CAMPAIGN_REBASELINE_20260902.json`, and the pre-rebaseline snapshot remains under `docs/forensics/`. Those artifacts are not loaded by normal startup and do not require a fresh checkout or fresh recovery store after every deployment.

## Deployment verification

Git commit, Railway deployment, campaign-state durability, MCP schema refresh, and installed Skill refresh are separate tiers. The packaged GM Skill carries a non-secret compatibility fingerprint that must be supplied to `get_play_context`; a stale installed Skill or cached MCP schema therefore fails closed instead of silently driving a newer runtime. Every authoritative `get_play_context` also re-runs the local deployment/source compatibility attestation, so a process that became stale after startup cannot emit a normal playable context with a green delivery proof. This proves the running process against its locally fetched refs, not that an unseen external Git change or Railway routing/domain change does not exist. After deployment, refresh the MCP schema and installed Skill together, then confirm `/health`, bounded OOC audit, and `get_play_context` all agree with the **current** `state/meta.json` before consequential play.

For a bounded repair handoff, run the inexpensive checks selected in its implementation notes, synchronize the Skill contract, and build the final artifacts with `python tools/package_release.py <source-output.zip> --skill-output <skill-output.zip>`. Both output paths must be outside the repository. The packager excludes transient caches/checkpoints, requires runtime/game/state/Skill/deployment surfaces, reopens and byte-compares the source ZIP, verifies that the separately installable Skill contains the identical files, and runs fast source/schema/release-state/Skill checks against the extracted source itself. `RELEASE_MANIFEST.json` identifies the source bytes and shipped baseline; it does not claim deployment occurred. See the [September 11 live handoff](LIVE_CHATGPT_VALIDATION_20260911.md).

The release-coupled token must now accompany both `get_play_context` and `preview_command`. Preview also requires `expected_campaign_id` copied from fresh context. Context can guard `expected_campaign_id` and `expected_baseline_id`, reports component hashes and installed dependencies, and rejects incompatible pinned versions. A production environment missing a valid image SHA is unavailable; a local unmarked environment remains usable but reports no deployment proof.

## Transactions and recovery

Persistent writes retain exact expected revision, preview attestation, one semantic command per transaction, atomic staged writes, conservation checks, Git durability, WAL/receipt idempotency, and fail-closed retry/recovery.

A volume wipe is justified only for an explicit rebaseline, proven unrecoverable corruption, or another deliberate operator action with a documented migration plan. It is not routine deployment hygiene.
