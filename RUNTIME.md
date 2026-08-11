# Sword & Banners Runtime

Sword uses an independent deterministic Python runtime under `runtime/sword_runtime/`. It does not import Shinobi code or state at runtime.

A production consequential action follows:

`intent -> semantic command -> bounded owner closure -> due causal settlement -> reducers -> schema/invariant validation -> WAL -> atomic owner replacement -> exact Git staging -> local Git commit -> configured remote push and verification -> durable receipt -> player-safe result`

The world scheduler is the bounded event queue in `state/runtime.json`. Each causal host stores `resolved_through`, `safe_through`, `next_due`, and recurrence information. Recurring work is compacted arithmetically. Ordinary production settlement does not scan every person, faction, force, or House.

## Production durability

Hosted play uses `runtime/sword_runtime/service_runtime.py`. Production wires `GitRemoteDurability` inside the transaction coordinator and disables the legacy post-receipt best-effort replicator.

A local Git commit is not enough for a new hosted gameplay write to be reported as committed. The configured production branch must accept and verify the exact transaction commit before the durable receipt is published. Remote failure remains recoverable transaction work rather than successful gameplay followed by silent replication debt.

Local/core runtime construction remains available for isolated deterministic fixtures and tests where no production remote is configured.

## Recovery

Transaction recovery is bounded by interrupted work, not campaign age. Runtime WALs live under the configured runtime root. Only pending work is inspected during ordinary recovery; terminal WAL history and hash-addressed receipts are retained for audit and idempotency without requiring full historical scans.

Railway stores the live Git checkout at the persistent campaign root and operational WAL/lock/receipt data at a separate persistent runtime root.

Bootstrap is fail closed. It fast-forwards a clean checkout when the remote is ahead, preserves a clean local-ahead transaction so recovery can finish it, and refuses dirty conflicting state. If Git repository history is deliberately replaced while a persistent volume still has the previous lineage, bootstrap may adopt the new remote lineage only after verifying that the complete committed `state/` campaign-authority tree is identical. Divergent campaign truth requires deliberate repair.

## API and MCP

`runtime/sword_runtime/api/app.py` constructs one production runtime instance shared by recovery, REST compatibility routes, and the MCP operations layer.

The ChatGPT MCP surface is OAuth authenticated and exposes bounded tools for:
- current play context;
- exact permitted person reads;
- exact permitted object reads;
- command preview;
- exact attested execution;
- read-only OOC audit.

Deterministic commands can return projected preview results. Contested battle, personal-combat, and siege-assault commands deliberately hide their stochastic outcome during preview and resolve it once at execution.

## Deployment

Railway starts:

`PYTHONPATH=/app/runtime python -m sword_runtime.bootstrap`

Source and game-definition changes trigger deployment. Runtime-generated `state/**` gameplay commits are excluded from the deployment watch paths so successful play does not create a redeploy loop.

`state/` remains the committed mutable campaign truth. Git-backed committed history is the durable campaign record.
