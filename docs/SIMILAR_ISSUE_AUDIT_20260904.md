# Similar-Issue Root Audit — 2026-09-04

This ledger records the cross-game analogue audit performed after the original playtest repairs. Campaign `state/` was not edited.

| Failure family | Sword & Banners result / repair | Shinobi analogue | Verification |
| --- | --- | --- | --- |
| Cumulative/hidden roster used as current perception | Reproduced in personal-combat target selection: empty current knowledge could fall back to the exact hidden roster and an explicit hidden `target_ref` could reveal exact position. Current targetability now gates both AI/coarse and explicit player targeting. | Reproduced more broadly; Shinobi now separates cumulative `observed_refs` from live `current_contact_refs`, including target planning, defense identity knowledge, attack attribution, and reinforcements. | Sword focused targetability 3/3 and similar-issue message/visibility 12/12. Shinobi release slice 60/60 plus maintained split groups. |
| Message dispatch treated as receipt / fixed-delay telepathy | Reproduced across commission, command, family, generic reply, Qin institutional, institutional-process, and military-career channels. Remote messages now use geography-backed travel, saved dispatch endpoints, and recipient/player chase on movement. | Ransom/captivity channel reproduced stale-HQ delivery; fixed reroute before faction knowledge/response. | Commission 4/4; institutional/routing group 25/25; campaign command 25/25; player-story/Qin 33/33; military-career 15/15. Shinobi routing regressions included in 60/60 release slice. |
| Informational/offer bookkeeping promoted to hard turn wake | Reproduced for commission offers/evidence review and military-career delivery notices; informational progress no longer manufactures hard scheduler wakes. Durable choices remain in their exact decision owners. | Inspected House offer paths already gate the player-facing choice behind physical delivery; no new cousin reproduced. | Commission 4/4; military-career 15/15; institutional/routing 25/25. |
| Distinct scheduled work collapsed by over-broad idempotency | Reproduced for follow-on command requests sharing a scheduler host identity. Each request now has distinct host identity, preventing overwrite. | No matching new Shinobi route/message host collision reproduced. | Command decision lifecycle 8/8; command contact/cycle/request 25/25. |
| Runtime/schema drift | Reproduced for interaction-attempt `origin_location_ref` and formation `military_allegiance_state`; closed schemas updated with the runtime owner. | Exact-combat closed template updated with Shinobi's new `current_contact_refs`; structural gate validates it. | `quick_check.py`: PASS (1397 JSON, 236 registered schemas); allegiance local/remote regression in 12/12 similar-issue module. Shinobi `quick_check.py` green. |
| Remote force mutation bypasses physical command | Reproduced in `military_allegiance_action`. The actual command-surface MRO short-circuited parent authorization; co-location validation now lives on the true command authority. Remote mutation fails closed absent a physical command-message route. | No matching new remote-force mutation reproduced in inspected Shinobi hard-consequence paths. | Similar-issue message/visibility module 12/12; military-career loyalty 15/15. |
| Moving recipient invalidates original delivery endpoint | Reproduced in command and institutional channels. Arrival at an obsolete endpoint reroutes/chases rather than creating receipt at a distance. | Reproduced in Shinobi ransom/captivity delivery and fixed with the same invariant independently. | Covered by command/contact/institutional routing suites and Shinobi causal-routing regressions. |

## Release invariants checked

- No cross-game imports, state, IDs, or runtime dependencies were introduced.
- Exact roster knowledge is not current targetability.
- Dispatch is not receipt; remote information follows physical delivery authority.
- Informational deliveries do not become hard player wakes unless a genuine irreversible response boundary exists.
- Closed schemas and runtime writes remain in parity.
- The uploaded campaign `state/` tree remains byte-for-byte unchanged.
