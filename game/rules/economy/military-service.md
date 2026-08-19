# Economy Module: Military Service

## Demography, labor, and recruitment headroom
A materialized settlement stores conserved age bands, dependents, fit military-age adults, medical restrictions, current service, agricultural labor, skilled craft labor, transport, administration, care labor, temporary unemployment, prior military experience, and exact unmaterialized potential-tier distributions.

Recruitment has three quantity ceilings:

- `Voluntary Ready Ceiling`: likely immediate respondents under the current offer;
- `Paid Expansion Ceiling`: additional eligible people reachable through time, credible pay, family support, and replacement labor;
- `Emergency Levy Ceiling`: coercible people whose removal immediately harms production, tax, loyalty, and households.

It also has a quality ceiling. A troop class's admission standard must be filled from the saved available potential and prior-experience pools. Elite selection can improve accepted quality only by increasing screening volume, time, cost, and rejected candidates or by transferring proven soldiers.

Ordinary recruitment headroom is calculated by `game/data/mechanics/economy.json`.

Every enlisted recruit transfers one exact source occupation and one exact potential tier. Recruitment above paid expansion ceiling creates immediate labor and political consequences. Overlapping campaigns reserve candidates so the same people cannot be promised twice.

## Recruitment campaign entry cost

A campaign owns one budget and one candidate reservation ledger. Before enlistment, calculate:

Campaign fixed recruitment cost is calculated by `game/data/mechanics/economy.json`.

Contacted-candidate outreach costs are registered in `game/data/mechanics/economy.json`.

Ordinary screened-candidate cost is registered in `game/data/mechanics/economy.json`; specialist screening adds its actual committed cost.

Entry cost per enlisted recruit is calculated by `game/data/mechanics/economy.json`.

Rejected, missing, and deserting candidates still consume contact, screening, travel, food, and administration already used. Equipment is purchased or issued only when custody transfers; unused stock remains inventory.

Default contract overlays are formation-level. The complete service-model terms and numeric overlays are defined only in `game/data/mechanics/career.json`; the selected model's costs are consumed by `game/data/mechanics/economy.json`. A service model is neither a faction-wide label nor a stat multiplier.

Selected ranker pay is calculated by `game/data/mechanics/economy.json`.

This ratio preserves each current formation contract at its registered cost while allowing another formation using the same troop class to adopt a different legal and economic contract. Entry cost is recomputed from class equipment/training inputs plus the selected model's bounty, advance, family support, route, and local prices.
Coercive recruitment may omit bounty, but it cannot omit transport, muster, rations, supervision, equipment, training, lost labor, resentment, desertion, and household hardship.

## Service establishment and payroll

A troop class defines combat role, doctrine, base pay preview, officer ratio, support establishment, equipment bill, ammunition issue, and training requirement. It stores a default model only for current historical pricing. The formation service contract, not the class and not the whole army, owns current pay terms, family policy, loot policy, casualty compensation, discharge, and demobilization.

Default anonymous rank structure and support-role monthly pay are defined only in `game/data/mechanics/economy.json`. Named officers and specialists use exact contracts and are never paid twice through anonymous establishment. Support people must exist in exact roles. A cavalry formation without enough grooms and farriers loses horse readiness; a formation without drivers cannot claim full wagon throughput; a river force without boatmen cannot operate all hulls.

## Army service models and player choice

An army is a mixture of formation-level service models, not one global label and not a permanent property of the troop class. Tang Wei chooses an actual model when forming a unit, accepting a sponsored command, or reforming an existing formation. `CREATE TROOP CLASS` may choose only its default pricing preview. The choice occurs through `ARMY MODEL`, `FORM UNIT`, the class-creation flow, or a natural-language order. The interface previews legal access, source population, first deployable date, entry cost, monthly cash and in-kind burden, training path, readiness, labor loss, loyalty basis, loot rights, casualty obligations, mobilization, and demobilization.

Supported models include state professional, frontier professional, provincial professional, state patrol/garrison, household retainer, mercenary contract, caravan contract, volunteer campaign, seasonal militia/levy, religious militia, irregular raider, clan warband, military colony, and allied contingent. A force may combine a professional core, seasonal levy, mercenaries, allied contingents, and military farms if each has a real owner and contract.

For a simpler player interface, group them into five families and show only models whose prerequisites are currently plausible:

1. standing/official: state, frontier, provincial, patrol/garrison;
2. personal/commercial: household, mercenary, caravan;
3. temporary/cause: volunteer, seasonal levy, religious militia;
4. kinship/irregular: raider, clan warband;
5. land/political: military colony, allied contingent.

The grouping is presentation only. The underlying contracts remain distinct because their authority, costs, readiness, loyalty, labor effects, and exit rules differ.

Model tradeoffs are enforced:

- standing professionals provide high readiness but continuous payroll, family, facility, and supply burden;
- patrol and garrison troops trade strategic mobility for local authority and recurring duty;
- household retainers emphasize personal loyalty but require durable patronage and dependent support;
- mercenaries mobilize quickly but demand advances, credible pay, loot terms, and exit rights;
- seasonal levies lower peacetime cash cost while removing farm labor and accepting slower muster, short service, and weaker cohesion;
- volunteers depend on a cause, campaign, and leader credibility and may dissolve when the cause or term ends;
- military colonies provide households, land, and food over years but cannot farm and campaign at full capacity simultaneously;
- allied contingents remain owned and partly supplied by another authority, creating divided command and political bargaining;
- clan, religious, and raider forces depend on kinship, belief, loot, fear, or local leadership and cannot be converted into obedient professionals by renaming.

Choosing or changing a model does not create people, money, land, equipment, authority, or loyalty. Reform is a timed project. Every entrant still begins the receiving class as a recruit and progresses sequentially.

## Formation operating ledger

Every formation and unassigned reserve owns a projected and realized operating ledger. Costs are derived whenever personnel, mode, equipment, animals, facilities, route, contract, or prices change.

Cash payroll is calculated by `game/data/mechanics/economy.json`.

Monthly food demand is calculated by `game/data/mechanics/economy.json`.

Monthly fodder demand is calculated by `game/data/mechanics/economy.json`.

Monthly maintenance reserve is calculated by `game/data/mechanics/economy.json`.

Monthly cash burden is calculated only by `game/data/mechanics/economy.json`; exact committed costs not represented by its named standard inputs must be recorded under the registry's explicit other-committed-cost channel before settlement.

Operating-mode pay/hazard, maintenance, medical/replacement, and transport factors are defined only in `game/data/mechanics/economy.json`.

Mode changes do not rewrite base pay. They add only supported hazard, wear, supply, and transport obligations.

The ledger shows current cash, food, and fodder runway. A projected reserve is not spent until a transaction occurs, but leadership must respond when the forecast crosses payroll, food, or maintenance failure.

## Military agriculture and soldier households

A military colony or farm owns land, households, labor schedule, seed, tools, animals, irrigation, housing, stores, defense, and harvest. Soldiers do not simultaneously provide full-time field readiness and full-time agricultural labor.

Farm output is calculated by `game/data/mechanics/economy.json`.

Training days, patrols, mobilization, wounds, and battle deaths reduce available farm labor. Mobilization during planting or harvest applies the exact missed-work loss. Output first covers seed, household consumption, animal feed, tax, and spoilage. Only the remainder becomes military supply or saleable surplus.

Military agriculture lowers cash food purchases but increases fixed land, household, infrastructure, and defense obligations. It is a long-term base, not instant free provisions.

## Sustainable military capacity
Sustainable force ceiling is the minimum-gate calculation in `game/data/mechanics/economy.json`.

Every capacity is converted to people for the intended class, service model, quality standard, and operating mode. The interface shows the limiting constraint and the next constraint.

A population may support a large levy but only a small trained army. A treasury may afford salaries but lack instructors, horses, equipment, or capable candidates. Elite formations cannot expand faster than their feeder pool and cadre can screen, train, and integrate. Heroic individuals are never a scalable capacity input.

### Executable sustainable-force ceiling

Convert each constraint independently to a number of soldiers for the intended class and operating mode: three-month pay runway, food after civilian needs, recruitable people, complete equipment sets, officer span, support capacity, facilities, transport, route access, and political tolerance. The sustainable ceiling is the minimum and records the limiting factor. Expected revenue and uncollected taxes do not fund the ceiling until realized.

Force changes use a pipeline. Ready reserves mobilize first, then already-training units complete legal certification, then new people enter `limited_duty`. Demobilization likewise takes time to settle pay, wounds, custody, equipment, households, contracts, transport, and reserve status. A posture decision never turns a desired number directly into active soldiers.

## Goal- and budget-driven force posture

At every monthly close and every exact threat, contract, war-goal, harvest, insolvency, or demobilization trigger, each force-owning institution calculates one target active force.

Desired force is calculated by `game/data/mechanics/economy.json`.

Feasible force is calculated by `game/data/mechanics/economy.json`.

Force-posture hysteresis thresholds and the hold/recruit/demobilize bands are defined only in `game/data/mechanics/economy.json`. Any resulting change still requires a real recruit, recall, levy, transfer, contract, discharge, demobilization, or merger process. Emergency mobilization may raise the target only within actual people, authority, money, food, equipment, route, officer, and time limits.

Recruitment and disbanding are not instant labels. Recruitment uses the complete candidate, household, labor, muster, entry-cost, training, equipment, and deployment process. Demobilization settles wages, arrears, equipment custody, wounds, prisoners, family support, route home, reserve status, household/labor return, and political consequences. A faction may keep an unaffordable force only by accepting debt, arrears, confiscation, desertion, readiness decline, or another exact consequence.

## executable realization and arrears

Realization factor is calculated and clamped by `game/data/mechanics/economy.json`. Apply it separately to every recurring source. In-kind receipts enter their physical ledger and do not become cash without sale and delivery.

Obligations settle in saved priority order. Payment is capped by available compatible resources. Any unpaid balance becomes exact arrears with obligation ID, amount, and age. Arrears create pressure through the owning service, household, supplier, or formation rather than directly subtracting an arbitrary morale value.

