# Tests

The canonical Gold release gate is:

```bash
python tools/run_gold_suite.py
```

It runs the production audit plus the complete deterministic runtime suite: architecture/service, transactions/recovery, long-horizon scheduling, real-campaign acceptance, semantic command surface, adversarial Gold hardening, and warfare. Third-party pytest plugin auto-loading is disabled, disposable campaign clones suppress Git background maintenance, and the module runner exits on pytest's exact status so host telemetry or shutdown threads cannot hold CI open after a result is known.

The same command then runs the mandatory persistence soak gate: two independent 1,000-transaction campaign replays from the same pristine commit. Both must finish with zero failures and zero global scans, leave no pending WALs, produce the exact same final state hash, and keep the final-200/first-200 transaction latency ratio at or below 1.35 with bounded 100-transaction window spread.

The hardening suite specifically blocks forged player/NPC authority, unlawful organizational commands, formation material duplication, non-causal battles, nonexistent personal-combat opponents, time-free training/recovery, duplicate relationship authority, unrouted mutable owners, obsolete CI release gates, and full-history WAL recovery scans.
