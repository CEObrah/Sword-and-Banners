# Logistics and Supply

`game/data/mechanics/logistics.json` is the structured numerical authority for ration endurance, forage, travel, throughput, sale price, and delivered quantity.





## Supply accounting

Person-days of food are calculated by `game/data/mechanics/logistics.json`.

Horse-days of fodder are calculated by `game/data/mechanics/logistics.json`.

Water is tracked explicitly on routes or camps where resupply is not reliable. Named animals, prisoners, wounded, servants, and camp followers consume supplies.

Daily consumption is deducted at the time crossed. Reduced rations create hunger, fatigue, illness, morale, desertion, and animal-condition effects rather than free endurance.

A supply source is usable only if stock can reach the consumer through a valid route with transport, drivers, guards, time, and authority.

## Water, forage, requisition, and local depletion

Water demand is stored as an exact planning rate for the current climate and workload. Baseline water-planning constants are defined in `game/data/mechanics/logistics.json`; heat, exertion, wounds, cooking, washing, and medical use must be saved as explicit adjustments. A river, well, or spring is not automatically safe, accessible, uncontested, or fast enough for an army.

Foraging and requisition transfer existing local stock. A locality stores accessible surplus, protected reserves, owners, harvest timing, transport, security, and recovery rate.

Forage yield is calculated by `game/data/mechanics/logistics.json`.

Collection capacity comes from real foragers, animals, carts, time, and supervision. Voluntary purchase spends money. Legal requisition creates receipts or obligations. Coercive seizure creates fear, resentment, concealment, flight, resistance, political cost, and future scarcity. Repeated collection reduces the exact surplus and may destroy seed, breeding stock, or household survival. The same village cannot feed every passing army from an abstract reset.

## Travel calculation

Route records own a favorable-condition `base_light_party_days` and distance. Actual time:

Travel time is calculated by `game/data/mechanics/logistics.json` using saved factors and splits when those factors materially change.

Party size, movement mode, load, terrain, weather, caution/security, injury, fatigue, and baseline water-planning constants are defined only in `game/data/mechanics/logistics.json`. Physically impassable routes are illegal rather than converted into arbitrary delay multipliers. The slowest essential element controls unless the force explicitly splits.

Scouting and guides reduce search, navigation, ambush, and route-choice delays. They do not erase distance.

## Route events, strategic crossings, and camps

Long movement resolves departure, route segments, water/food crossings, rest, weather, security contacts, animal condition, and arrival. Armies require camps, sanitation, watch, forage/requisition policy, baggage security, and deployment time.

Strategic rivers are not generic road terrain. The four currently authored major water crossings store exact game-simulation river width/depth/current, bridge span/width/load capacity, ferry count/payload/cycle and ford availability in `game/data/world/routes.json`. `state/geography/strategic-crossings.json` owns only mutable water stage, bridge condition, serviceable ferries and ford state. Road capacity and crossing capacity combine as a physical bottleneck. Destroying every viable bridge/ferry/ford path closes that route; damage reduces throughput and therefore increases column-clearing time rather than deleting or capping army bodies.

A materially moving recursive army uses one exact aggregate army-train owner under `state/logistics/army-trains/`. The train owns conserved cart teams transferred from an accessible depot. Food, fodder, ammunition and engineering stores remain owned by each formation's existing logistics ledger and are referenced by custody pointer rather than copied. Cart drivers and baggage guards are temporary aggregate duties borne by already-conserved army personnel, not new camp-follower bodies.

On arrival the same train persists the camp arrangement: headquarters, baggage park, animal lines, kitchens, sanitation, medical area, pickets and a temporary-depot custody view. Wagon damage, permanent wagon loss, baggage delay and relief-corridor routes persist on the train. Routine individual wagons are never materialized one-by-one. A standalone formation that undertakes strategic `formation_move` materializes the same bounded train model under its own formation authority: exact cart teams leave an accessible depot, drivers/guards are duties from its existing personnel, formation logistics remain cargo authority, wagon damage/delay persists, and arrival produces the same bounded camp/temporary-depot arrangement. Joining a recursive army does not duplicate that cargo or create extra people.

## Transport capacity

Transport load includes equipment, food, water, ammunition, tents, tools, money containers, cargo, wounded, bodies, prisoners, and loot.

People, horses, mules, wagons, carts, boats, and ships use their standardized capacities. Drivers and handlers are conserved personnel. A captured wagon without a team, driver, route, repair, and guard is not usable transport.

When capacity is exceeded, choose among abandoning, caching, selling, dividing, requisitioning, repairing, sending a convoy, reducing supplies, releasing prisoners, or slowing. Nothing enters an invisible inventory.

## Convoys, depots, maintenance, and route throughput

A depot owns stock, storage capacity, guards, labor, records, spoilage, fire risk, route links, loading capacity, and issue authority. A convoy owns exact vehicles or vessels, draft animals, drivers, guards, cargo, route, schedule, spacing, repair stock, orders, and destination custody.

Route throughput is the minimum-gate calculation in `game/data/mechanics/logistics.json`.

Movement beyond throughput requires multiple columns or cycles and creates delay, congestion, separation, or exposure. Army supply is limited by delivered stock, not stock existing somewhere in the realm.

At each daily or damaging review, vehicles, tack, vessels, shoes, wheels, axles, harness, and containers lose condition only from supported distance, load, terrain, weather, impact, fire, or neglect. Repair consumes parts, tools, labor, and time. A broken axle can halt one wagon without halting a whole army if cargo can be redistributed within real spare capacity.

## Prisoners and wounded

Prisoners require identity or unit, custody, restraints, guards, food, water, medicine, housing, route, and legal status. Guard requirement begins at one reliable guard per five ordinary unarmed prisoners and rises with dangerous officers, hostile terrain, weak restraints, or escape support.

Wounded and prisoners compete with loot for transport. Ransom, exchange, parole, recruitment, release, trial, labor, hostage use, and execution follow law, authority, relationship, information, and consequences.

## Prisoner security, escape, parole, and exchange

A prisoner body records guards, restraint condition, enclosure, route, health, food, allies, local support, intelligence value, legal status, and separation from weapons. Escape is an opposed extended action using access, Stealth, Athletics, Intelligence Operations, tools, help, guard quality, watch routine, and time. One unnoticed opening may create progress; it does not teleport a prisoner beyond the perimeter.

Parole requires identity, terms, guarantor or reputation, witnesses, permitted destination, reporting or non-service obligation, and breach consequences. Exchange and ransom require authority, proof of custody, negotiation, safe transfer, payment custody, and receiving party. Released people still need a route, supplies, and protection.

## Market transaction

Every sale needs a buyer with cash, demand, storage, legality, and access.

Unit sale price is calculated by `game/data/mechanics/logistics.json`.

Fixed anchors:

- condition: 0.20 scrap, 0.50 repairable, 0.80 worn serviceable, 1.00 sound, up to 1.10 excellent;
- scarcity: 0.75 oversupplied, 1.00 ordinary, 1.25 scarce, 1.50 crisis demand;
- legality: 0.40 dangerous stolen goods through a fence, 0.70 questionable, 1.00 clean, 1.10 authenticated high-demand state purchase;
- bulk: 1.00 within depth, 0.85 at twice depth, 0.65 at five times depth, or no buyer beyond storage/cash;
- bargaining/tax: resolved from Trade, relationship, office, fees, and evidence using fixed levels.


## Supply procurement and in-kind support

An army replenishment order identifies payer, buyer or issuing depot, commodity, quantity, price or tax basis, source stock, destination, route, carrier, escort, loading capacity, departure, expected arrival, spoilage, and custody. Payment without source stock does not create goods. Goods without transport do not enter formation inventory.

Delivered quantity is calculated by `game/data/mechanics/logistics.json` and cannot fall below zero.

In-kind tax, patron grain, estate output, requisition, and allied supply use the same transfer procedure. Their silver-equivalent value is reported separately and never added to cash.

A depot records stock by lot, owner, quality, condition, storage capacity, spoilage risk, guard, and route access. Convoys and depots may reduce purchase frequency but add guards, animals, wagons, handlers, storage losses, and capture risk.

## Army budget and revenue views

`ARMY BUDGET`, `LEDGER`, or `REVENUE` shows:

- current cash and restricted reserves;
- monthly combatant, officer, named, support, family, facility, maintenance, medical, transport, training, replacement, and debt burden;
- food person-days and fodder animal-days required, stored, due, and missing;
- recurring cash income by source;
- recurring in-kind support by source;
- seasonal, contractual, one-time, emergency, and borrowed resources separately;
- projected cash surplus or deficit, payroll runway, food runway, fodder runway, next collection, next harvest, and earliest failure threshold;
- the current sustainable-force ceiling and limiting dependency.

The view never treats inventory value, receivables, credit, or expected loot as spendable cash.

## Payroll and arrears

Payroll records pay period, eligible personnel, rate, bonuses, deductions, family support, arrears, paymaster, and treasury. Payment transfers money at the due time. Unpaid troops accumulate grievance according to contract, need, alternatives, loyalty, leadership, and duration; they do not instantly mutiny on a generic timer.

## Logistics review

At departure, dawn, major supply event, and after battle, reconcile mouths, animals, person-days, horse-days, water, ammunition, medical capacity, payroll, transport, route, and expected arrival. `SUPPLY` shows the limiting resource first.

## equipment resolution

## persistent-force-logistics-clocks

A force lifecycle cannot remain active without a supply source or explicit shortage state, payroll owner or lawful unpaid status, inventory owner, transport basis, and next logistics review. Stationary offscreen aggregate forces may batch stable consumption and maintenance at a monthly close; moving, campaigning, besieging, starving, damaged, or disease-exposed forces review at daily or material milestones.

Every force lifecycle consumes only delivered food, fodder, water, ammunition, repair stock, transport, labor, and money. Failure propagates to condition, fatigue, readiness, morale, desertion, illness, movement, and operational choices rather than being ignored.
