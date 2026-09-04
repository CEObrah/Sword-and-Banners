# Formation and Army Combat

`game/data/mechanics/formation.json` is the numerical authority for frontage, formation margins, contact opportunities, integrity penalties, exchange timing, reserve commitment, pursuit, casualty-rate arithmetic, and formation capability means. `game/data/mechanics/combat.json` and `game/data/mechanics/injury.json` resolve representative physical contacts. `game/data/mechanics/morale.json` owns morale pressure and rally.

This file defines formation legality, temporary formation-state ownership, sequencing, command, reserves, and casualty conservation. A formation owns only its current arrangement/operation state; source units own personnel and persistent capability. It does not redefine structured numerical tables.

## Scale and frontage

Small consequential groups resolve exact people plus compact units. Formations resolve actual engaged frontage, equipment readiness, morale, cohesion, officers, terrain, supply and orders. Armies resolve sectors, objectives, reserves, communications, routes, logistics and politics.

Only bodies with a legal physical contact lane contribute to the engaged front. Rear ranks may replace, brace, carry ammunition, support formations, guard flanks, or remain reserve according to doctrine.

## Operational formation state

A deployed formation or sector stores:

- owner and source allocation;
- named attachments;
- commander and succession;
- objective;
- location/route/facing;
- fit count and engaged frontage;
- reserve count;
- integrity, cohesion and morale;
- supply and ammunition;
- fatigue;
- casualties and prisoners;
- retreat routes;
- initial fit strength;
- contact carry;
- current orders and information.

Named people remain exact even when attached to a large formation.

## Current capability

Underlying capability comes from the source units attached to the formation and their current authoritative capability state plus later settled development. The formation has no permanent stat owner of its own. Qualification is a legality/procedure gate, not a second hidden stat multiplier. Experience modifies execution through the structured training/formation registries and is applied once.

A derived current-capability cache is not independent authority. Any material change to personnel, certification, experience, development or standard invalidates the cache.

## Contact opportunities

Formation Margin maps to the registered contact fraction in `game/data/mechanics/formation.json`. That fraction creates potential contacts only.

Potential contacts then resolve through actual:

- weapon and shield issue;
- armor;
- anatomy;
- horse state;
- target exposure;
- terrain;
- declared method.

A contact opportunity is not automatically a casualty. Unexposed bodies cannot be hit by ordinary melee simply because the formation is large.

Contact carry persists only while the same continuous physical contact line remains.

## Exchange time

Each exchange advances real time. Standard stable exchange intervals are registered in `game/data/mechanics/formation.json`; ranged cycles use actual weapon cycles and maneuvers use actual route/work time.

An exchange must split when casualties, morale, fatigue, ammunition, orders, arrival time, terrain, formation integrity, or command materially changes inside the interval.

Every involved tranche receives complete exertion or recovery coverage for the elapsed time.

## Formation integrity

Integrity states are:

`ordered -> pressured -> distorted -> fragmented -> broken -> routing`

The structured registry owns their numerical execution consequences. Ordinary pressure changes integrity progressively. Catastrophic physical events may produce a larger immediate transition when the exact cause is committed.

Routing formations have no coherent offensive method until valid rally/regrouping occurs.

## Morale

Formation morale uses `game/data/mechanics/morale.json` only. Casualties, command loss, flank/rear state, isolation, supply, registered fear effects, cohesion and explicit rally actions create the pressure/result.

No separate formation-only morale formula may override it.

## Ranged formations

A ranged group needs actual shooters, weapons, ammunition, frontage, line of sight, doctrine and legal release time. Ammunition expenditure occurs before wound results. A group without ammunition uses its registered fallback or becomes unable to fire.

Representative projectile contacts use the personal/ranged combat kernel and do not reroll after accuracy/contact has been fixed.

## Cavalry and charges

A charge group requires fit mounts, compatible tack/barding, legal load, trained riders, sufficient lane and a valid exit path. Rider weapon contacts, horse collision, horse wounds, rider balance, falls and final positions are resolved separately.

A formation does not gain a charge merely by carrying the cavalry label.

## Reserves, relief, and replacement waves

A reserve requires a valid commander or standing trigger, current information, route and space. Commitment time is the registered order delay plus movement time.

Reserves replace only removed frontage bodies through an open route. Replacement personnel retain their own experience, equipment, health and capability rather than inheriting the front line's veteran status.

Relief physically moves incoming and outgoing bodies and can itself create disorder or enemy exploitation.

## Withdrawal and pursuit

Withdrawal requires a route, order or standing trigger, movement capacity and enough cohesion to execute the chosen method. Pursuit requires actual mobility, information, control and route access.

Pursuit score is calculated by `game/data/mechanics/formation.json`. A successful pursuit still resolves physical contacts and cannot capture bodies the pursuer cannot reach.

## Casualties and cumulative shock

Casualties are exact conserved changes to the source population. Dead, wounded, captured and missing remain separate states.

The registered casualty-rate formula is used only to evaluate current formation shock and thresholds. It never replaces actual casualty counts.

Reinforcements change the denominator only when they physically join and the formation state records the new engagement basis.

## Named-person battlefield exposure

Named people do not receive plot armor from being exact records. Exposure comes from their actual position, duty, orders, weapon range, mount, body geometry, enemy attention and local formation state.

A commander at headquarters is not automatically exposed to every frontline contact. A commander personally entering a charge becomes physically exposed.

## Command and appointments

Command requires a valid appointment or recognized emergency succession. Orders require communication and time. A commander may improve decisions through actual skill and staff capacity but does not add personal combat stats directly into every soldier's permanent sheet.

If command is lost, succession uses saved appointments/standing orders and the morale system.

## Formation construction

A formation is an assignment of conserved people, equipment, animals and command. Splitting or merging must conserve every source claim. Formation doctrine and familiarity persist only for personnel who actually learned them.

No operational arrangement, battlefield assignment, command-group nesting, or doctrine choice creates extra soldiers, horses, ammunition, or equipment.

## Unit execution

Combat resolves directly by unit. Each participating unit owns one troop type, its permanent aggregate capability distributions, and current local state such as surviving headcount, position, facing, order, integrity, fatigue, morale, cohesion, equipment condition and ammunition.

The deterministic combat kernel may calculate representative contacts internally for efficiency, but those calculations do not create another persistent organizational object beneath the unit. Different troop types are never averaged together.

A named commander is resolved outside anonymous unit headcount. The command mechanics apply that person's relevant command/tactical capability to the units actually under that command relationship; the commander does not become part of the unit's average soldier statistics.

## Post-battle settlement

After contact, commit:

- dead/wounded/captured/missing;
- fatigue;
- morale and cohesion;
- ammunition;
- equipment and animal losses;
- command changes;
- battlefield control;
- movement/retreat;
- supply consequences;
- next operational review.

A formation may not retain its pre-battle readiness or inventory after material losses.


## Service-support frontage
Only frontage-eligible or explicitly committed combat units contribute default assault contact. Medical/logistics/signal/service units remain targetable and casualty-bearing but do not increase line frontage by being attached to the army. Engineers/scouts are combat-support and affect engineering/reconnaissance first; if explicitly committed, resolve their actual combat ability rather than treating them as line infantry.
