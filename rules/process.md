# Autonomous Processes and Temporal Settlement

`RUNTIME.md` owns the transaction and full catch-up procedure. `data/runtime/temporal-settlement.json` owns recurrence, batching, residual accrual, successor-plan, trigger, and closure mechanics. `state/time/frontier.json` owns the current process frontier.

Every evolving owner must have direct or aggregate process coverage. A due process is not considered caught up after only one overdue cycle. Settlement continues through every due boundary and, for continuous accrual, through the exact reached world time.

Player-required consequential decisions are hard interrupts unless saved standing orders or delegation lawfully resolve them.
