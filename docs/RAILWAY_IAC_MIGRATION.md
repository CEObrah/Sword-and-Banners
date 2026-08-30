# Railway Infrastructure-as-Code migration

Sword & Banners currently uses the legacy root `railway.toml` Config-as-Code file. Railway has deprecated that mechanism and documents a hard cutoff for existing legacy services on **2026-12-01**. The replacement is Railway Infrastructure as Code in `.railway/railway.ts`.

Do **not** hand-convert the repository file in isolation. Railway's IaC migration must begin from the actual linked project/environment so service identity, environment-specific settings, variables, volume/network configuration, and other dashboard-owned state are not guessed or silently discarded. Railway also documents that a service must not be managed simultaneously by legacy Config-as-Code and IaC.

## Required migration procedure

Run this only from an authenticated, correctly linked Railway CLI workspace for the production Sword & Banners project:

1. Confirm the linked project, environment, and service are the intended production owners.
2. Run `railway config pull --force` to import the current Railway project state into `.railway/railway.ts`.
3. Compare the imported service configuration against the still-active `railway.toml`, preserving the Sword runtime requirements:
   - Railpack builder;
   - source watch exclusions for `state/**`, Skill/docs/tests/tools/CI-only changes;
   - `PYTHONPATH=/app/runtime python -m sword_runtime.bootstrap` start command;
   - `/health` health check with sufficient startup timeout for Git reconciliation, integrity validation, and recovery;
   - current restart, overlap, and draining policy;
   - persistent volume and all existing environment/network settings from Railway itself.
4. Remove `railway.toml` only in the same migration change that makes the imported IaC authoritative. Never leave both systems managing the same service.
5. Run `railway config plan` and inspect the complete plan. Unexpected service deletion/replacement, volume changes, networking changes, variable removal, or source changes block the migration.
6. Apply with `railway config apply` only after the plan is understood and intentional.
7. Redeploy and verify `/health`, the authenticated OOC deployment attestation, persistent campaign revision/time, remote durability, and a read-only `get_play_context` smoke check before resuming writes.

## Repository boundary

This document is preparation, not proof that Railway has been migrated. A GitHub merge cannot establish or modify the linked Railway project's current IaC state by itself. Until an authenticated Railway migration is performed and verified, the legacy `railway.toml` remains the active repository deployment configuration.

References: Railway documentation for Config as Code deprecation and the Railway CLI `config pull`, `config plan`, and `config apply` workflow.
