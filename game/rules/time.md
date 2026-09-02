# Time and Historical Calendar

`RUNTIME.md` and `game/data/runtime/temporal-settlement.json` own advancement and full catch-up. This file defines Sword and Banners calendar semantics only.

The campaign uses exact historical-style BCE timestamps with no year zero. Calendar month, quarter, and year recurrences preserve their registered boundary clock and move toward later historical time correctly across BCE years.

Travel, messenger, mobilization, construction, recovery, training, and campaign duration come from their routed mechanics and current state. Hidden events remain hidden until information reaches Tang Wei through a valid path.

Long skips may batch stable intervals but must split at material changes and player-required decisions. Continuous processes accrue through the exact reached time, including the final partial calendar interval.
