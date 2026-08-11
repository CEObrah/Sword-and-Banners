# Sword & Banners Runtime

Sword uses an independent deterministic Python runtime under `runtime/sword_runtime/`. It does not import Shinobi code or state at runtime.

A consequential action follows:

`intent -> semantic command -> bounded owner closure -> due causal settlement -> deterministic reducers -> schema/invariant validation -> WAL -> atomic owner replacement -> exact Git staging -> Git commit -> readback -> durable receipt -> player-safe result`

The world scheduler is the bounded event queue in `state/runtime.json`. Each causal host stores `resolved_through`, `safe_through`, `next_due`, and recurrence information. Recurring work is compacted arithmetically. The runtime never scans every person, faction, force or House during ordinary production settlement.

A valid local Git commit is canonical immediately. Optional GitHub replication is best-effort and retryable; remote failure does not roll back valid local gameplay.

Transaction recovery is bounded by interrupted work, not campaign age. Runtime WALs remain under `.sword-runtime/wal/`: only `pending/` is inspected during ordinary recovery, while receipt-backed committed and rolled-back WALs are atomically moved to `terminal/` for load-on-demand audit/history. Existing flat WAL histories are migrated once on startup. Idempotency receipts remain hash-addressed, so a normal command does not reread historical transaction records.

For deployment, Railway mounts the persistent campaign checkout and runtime metadata volume, then starts `python -m sword_runtime.bootstrap`. The private API exposes health, player-safe context, command preview/execute and read-only OOC diagnostics. MCP is an optional service transport over the same Sword runtime.
