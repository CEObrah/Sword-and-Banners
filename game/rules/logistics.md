# Logistics and Supply

`game/data/mechanics/logistics.json` is the structured numerical authority for travel, route throughput, baggage burden, sale price, and other registered logistics factors. `runtime/sword_runtime/military_supply.py` is the ordinary field-army supply authority.

## Civil food versus military supply

Agriculture remains part of the civil economy. Grain production, reserves, population demand, trade disruption, famine risk and siege endurance belong to settlement/state economy and fortified-site owners.

Ordinary field armies do **not** own ration, animal-feed or unified provisions inventories. They do not deduct rations every day or every battle contact. Current military support is a derived `strategic_supply` condition from exact physical facts including location, territorial control, reachable friendly strategic support, route condition, force size, mounted burden, civilian food stress and operational separation.

The standard supply bands are `secure`, `adequate`, `strained`, `poor`, `critical`, and `isolated`. Shortage affects movement, combat expression, recovery and mount condition at meaningful activity boundaries. Supply is recomputed from current authority rather than cached as a second mutable truth.

Animal feed is not a tracked military commodity. Pasture, season and horse-supporting terrain may influence mounted logistical burden through registered strategic factors, but they never create an inventory.

## Discrete military assets

Ammunition, weapons, armor/shields where present, siege equipment, engineering equipment, remount horses and other tactically discrete assets remain conserved by their exact owners. Running out of arrows or losing siege equipment changes capability because those are real physical assets, not an abstract supply score.

`resupply` transfers only registered discrete material from an exact accessible source to an exact formation. No ration or animal-feed issue is part of ordinary formation resupply.

## Army baggage and camps

An army's ordinary baggage travels with the army. There is no independent persistent army-train owner.

Baggage, carts, pack capability, support duties, medical transport, spare equipment and siege gear contribute to the army's movement/throughput burden. They do not become a second moving army with separate chronology merely because the formation marches.

A camp is the army's temporary operational posture at its current location. Headquarters, pickets, baggage area, animal lines, sanitation, medical area and ordinary camp functions are derived from the army and current situation unless a separately persistent fortification, depot, siege work or other physical object is actually created.

## Detached convoys

A convoy is materialized only when cargo is physically separated from both sender and recipient and therefore can independently move, be delayed, intercepted, captured or redirected. Once delivered, the convoy's cargo returns to the recipient's normal exact owner and the temporary transfer object should not survive merely as bookkeeping.

## Travel and route throughput

Route records own favorable-condition distance and travel inputs. Actual travel uses registered movement mode, party/army size, terrain, road quality, weather where material, fatigue, caution/security, baggage burden, crossings and the slowest essential element.

Scouting and guides reduce navigation/search/ambush risk where supported. They do not erase distance.

Strategic rivers use the exact crossing state in `state/geography/strategic-crossings.json`. Bridge, ferry and ford serviceability can close or constrain a route. Large forces may require multiple columns/cycles when route or crossing throughput is insufficient; bodies are never deleted or capped merely to fit the road.

## Water and exceptional subsistence

Routine army water is environmental planning, not a universal hot-state inventory. Explicit water state is material only where reliable access cannot be assumed, such as particular sieges, arid routes, quarantine/custody situations or other registered exceptional conditions.

Civilian famine, besieged-settlement starvation and other population food crises remain real because their food authority is the civil/fortified owner, not a field-formation ration ledger.

## Depots

Military depots exist where discrete stock or strategic storage is materially relevant: ammunition, replacement equipment, siege/engineering stores, remounts and similar assets. A city may also have civil grain storage for food security and siege endurance without converting every field army into a grain-transfer ledger.

Do not create depot layers merely to represent ordinary support that is already captured by strategic supply and route access.

## Prisoners and wounded

Prisoners and wounded remain real burdens. Custody, guards, health, movement, medical capacity, secure housing and transport matter. They compete for actual command attention and transport when movement occurs. Their ordinary subsistence should be represented at the minimum resolution required by the custody/settlement system rather than recreating formation-level ration accounting.

Ransom, exchange, parole, release, recruitment, trial, labor, hostage use and execution remain separate lawful consequences.

## Market transaction

Every sale needs a buyer with cash, demand, storage, legality and access. Price uses the registered condition, scarcity, legality, bulk and bargaining/tax factors. Inventory value, receivables, credit and expected loot are never spendable cash.

## Army budget and readiness views

Army/command logistics views should show decision-relevant constraints rather than grocery accounting:

- cash/payroll and arrears where material;
- strategic supply condition and why it is limited;
- route/crossing access and distance to support;
- ammunition and tactically discrete shortages;
- equipment/remount/medical/engineering constraints;
- baggage/transport burden;
- fatigue, readiness and earliest known operational failure or delay.

Do not show ration runways for ordinary field formations.

## Review cadence

Military logistics is reviewed at meaningful causal boundaries: movement planning/arrival, major route or territorial change, battle contact/aftermath, siege transitions, detached convoy events, or another action whose legality/capability depends on support.

Do not run daily global ration sweeps for every army. Stable offscreen formations need no logistics work merely because another day passed.
