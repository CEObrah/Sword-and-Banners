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

Current production does not expose a generic formation-wide "army model" switch. State professionals, House forces, temporary sovereign levies, allied commands, and mercenaries are represented by their actual owning force/cohort/contract systems. The only shared service-cost overlay currently read from `game/data/mechanics/career.json` is the mercenary cash-pay factor. Other military obligations come from the exact force, population, treasury, logistics, recruitment, and contract owners that already exist.

Selected ranker pay and ordinary professional wage inputs are calculated by `game/data/mechanics/economy.json`. Coercive levy service cannot erase transport, muster, rations, supervision, equipment, training, lost labor, exhaustion, resentment, desertion, or household hardship; sovereign levy calls additionally accumulate the compact mobilization-strain authority in `game/data/mechanics/settlement.json` and `runtime/sword_runtime/state_levy.py`.

## Service establishment and payroll

A formation's bodies, equipment, current ownership, command authority, logistics and any exact contract remain separate conserved facts. Named officers and specialists are never paid twice through anonymous establishment. Mercenary companies use exact contracts and a deterministic fair-pay floor. Sovereign levies use the dedicated temporary levy lifecycle and return surviving bodies and equipment on demobilization.

## Formation operating ledger

Every formation and unassigned reserve owns a projected and realized operating ledger. Costs are derived whenever personnel, mode, equipment, animals, facilities, route, contract, or prices change.

Cash payroll is calculated by `game/data/mechanics/economy.json`.

Monthly food demand is calculated by `game/data/mechanics/economy.json`.

Mounted forces increase the derived strategic-support burden; there is no separate feed-demand ledger.

Monthly maintenance reserve is calculated by `game/data/mechanics/economy.json`.

Monthly cash burden is calculated only by `game/data/mechanics/economy.json`; exact committed costs not represented by its named standard inputs must be recorded under the registry's explicit other-committed-cost channel before settlement.

Operating-mode pay/hazard, maintenance, medical/replacement, and transport factors are defined only in `game/data/mechanics/economy.json`.

Mode changes do not rewrite base pay. They add only supported hazard, wear, supply, and transport obligations.

The ledger shows current cash and material commitments. Field-force sustainability is evaluated through strategic supply rather than ration runways; leadership must respond when payroll, equipment, local food security, or strategic-support conditions become unsustainable.

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

