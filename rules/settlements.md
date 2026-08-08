# Settlements, Population, and Projects

`data/mechanics/settlement.json` is the structured numerical authority for settlement balances, production, labor progress, disease exposure, recruitment availability, and levy burden.





## Settlement state

Settlements track one conserved population owner plus materialized households and institutions. Core fields: total present population; age/sex/work bands where needed; food; wealth; disease; security; fortification; trade; crime; elite cooperation; legal claim; military occupation; administration; taxation; civilian loyalty; resistance; recruitment pool; production; storage; and route access.

Military occupation, legal claim, tax collection, road security, elite cooperation, and civilian loyalty are separate. Capturing a wall does not repaint surrounding villages.

## Population conservation

## Settlement review cycle

Food balance is calculated by `data/mechanics/settlement.json`.

Recruitment availability is calculated by `data/mechanics/settlement.json`.

This is an upper bound, not willingness. `rules/careers.md` resolves actual enlistment.

## Production

Production requires an owner, site, recipe, input stock, skilled labor, general labor, tools, capacity, time, fuel, quality control, and output storage.

Cycle output is calculated by `data/mechanics/settlement.json`.

Missing a critical input makes the recipe illegal. Any concrete equipment improvement depends on materials, pattern, craft skill, tools, supervision, inspection, and time; money alone cannot alter a physical field an incapable workshop cannot produce.

Agriculture responds to acreage, labor, seed, animals, weather, security, irrigation, and harvest timing. War, conscription, raids, and disease reduce labor and transport.
## Estate acquisition

An estate requires a legal grant, purchase, inheritance, marriage transfer, lease, occupation, or other recognized/coercive basis. Record land, boundaries, residence, tenants, debts, claims, control, income, storage, staff, garrison, and succession. Possession without recognized claim may invite litigation or war.

## Facility patterns

Facility baseline costs, materials, labor-days, base construction times, capacities, and monthly maintenance are defined only in `data/mechanics/settlement.json`. They are ordinary regional references before saved scarcity, land, transport, security, quality, and design modifiers. A custom facility must change cost, material, labor, capacity, condition, and maintenance together rather than receiving a free capability.

## Construction queue

Each project records design, owner, site, legal permission, required inputs, delivered inputs, total labor-days, assigned crews, skilled supervision, start time, progress, expected completion, condition, and blockers.

Daily progress labor is calculated by `data/mechanics/settlement.json`.

A site may have one primary project at full shared-site efficiency. Additional projects split labor, tools, supervision, and transport unless independent crews and stock exist. Construction advances only when time crosses and resources remain available.

## Facility operation

A completed facility still needs manager, staff, supplies, maintenance, security, and access. Capacity above safe limits raises wear, disease, fire, theft, escape, or training penalties. Damage changes condition and function until repaired.

## Institutional adaptation and failure

A recurring deficit, missing essential supply, or loss of legitimacy does not jump straight to collapse. Unless an exact crisis forces another result, pressure advances through supported stages:

1. arrears or unmet obligations;
2. ration, benefit, or service reductions;
3. deferred maintenance and equipment decline;
4. reduced training, patrols, production, or enrollment;
5. asset sales and reserve depletion;
6. debt, political concessions, or dependency;
7. coercive fundraising, predation, corruption, or illegal work when leadership permits;
9. internal conflict, mutiny, succession struggle, or factional split;
10. merger, absorption, surrender, dissolution, or disappearance.

Each stage posts exact money, stock, personnel, property, morale, legal, political, relationship, and reputation consequences. Recovery is possible when income, supplies, leadership, law, demand, or security changes. Dissolution preserves debts, survivors, property, secrets, enemies, successor claims, and one terminal receipt rather than deleting the institution.

## Estate and facility operating accounts

An operating estate records tenants or laborers, acreage or enterprise, inputs, output, household consumption, saleable surplus, wages or shares, tax, debt, manager, maintenance, security loss, storage, and treasury reference.

Estate net cash is calculated by `data/mechanics/settlement.json`.

In-kind production remains inventory until consumed or sold. A facility that lacks maintenance accumulates condition loss and capacity reduction at reviewed intervals. A profitable ledger does not imply physical food, tools, guards, or transport unless those owners exist.

## Regional generation

Province contracts materialize only what current travel, a due event, or a consequential relationship requires: county seat, town, village, fort, estate, ferry, camp, household, route, market, or local character.

Generation procedure:

1. identify province owner, terrain, population pool, existing nodes, and cause;
2. select a physically plausible location and settlement type;
3. transfer exact population, stock, authority, and household relationships from existing owners;
4. create at least one valid route and travel profile;
5. create market, production, security, and local power only at necessary detail;
6. add characters or forces only from conserved population and resources;
7. update province unmaterialized population and indexes.

A generated settlement cannot be a free source of money, troops, equipment, or information.

## Disease, sanitation, and outbreaks

A disease record owns syndrome, source or uncertainty, incubation window, infectious period, transmission route, severity distribution, known cases, exposed population, immunity or prior exposure if relevant, treatment capacity, sanitation, quarantine, deaths, recoveries, and next review. Do not identify a precise disease without evidence.

Exposure pressure is calculated by `data/mechanics/settlement.json`.

Population resistance is calculated by `data/mechanics/settlement.json`.

All components use fixed levels or a saved 0-100 institutional value. Disease margin, registered contact-fraction bands, new-case rounding, carry, and exposed-population caps are defined only in `data/mechanics/settlement.json`. Cases are not deaths. Each case unit advances through incubation, symptomatic review, recovery, chronic consequence, or death according to the disease contract and care.

Quarantine has a boundary, guards, supply, duration, legal authority, communication, and evasion pressure. Clean water, latrines, burial or burning, drainage, spacing, food inspection, insect control, and medical care consume labor and stock. Poor sanitation produces risk only after supported exposure and elapsed time; a dirty camp does not receive arbitrary instant casualties.

## Projects, activities, and retained results

A **project** is a persistent objective with design, authority, workfront, dependencies, required progress, consumed inputs, quality, manager, and completion conditions. An **activity** is one actual block of labor, travel, administration, negotiation, training, or supervision performed by real actors during exact time.

One fact is never owned by both:

- the project owns required and completed progress, dependencies, reserved resources, defects, quality, and terminal state;
- the activity owns attendance, workers, tools, start/end time, conditions, work score, consumed inputs, injuries, interruption, and the progress contribution;
- character development owns only retained personal credits supported by that activity.

Activity progress is calculated by `data/mechanics/settlement.json` and remains capped by real workfront/resources. for the lawful standard work block. Multiple workers contribute only within workfront, supervision, tool, material, and coordination capacity. A project cannot progress because time passed without an activity or valid stable routine batch.

Completed, failed, cancelled, destroyed, or superseded projects leave compact terminal receipts and leave current project registries.

## Layered manpower, levy cost, and demobilization

Province military ledgers route active service, household/local armed people, trained militia reserve, ordinary civilians, emergency-levy capacity, and follower/support capacity. Materialized settlements are local slices of those province owners. A regional mobilization may remain aggregate, but exact transfers must reduce the source layer before creating a host.

Compulsory service reduces cash pay, not total cost. Every mobilized person creates food, water, transport, supervision, equipment, medical, sanitation, administration, casualty, return-route, and household obligations. It also removes labor and may reduce harvest, craft output, tax collection, transport, care work, and future recruitment.

Levy total burden is calculated by `data/mechanics/settlement.json`.

Long duration, coercion, arrears, harvest timing, distance, poor supply, casualties, and broken promises raise hardship and desertion. Short local defense under trusted leaders may be sustainable with little cash. A distant campaign through harvest can be more expensive to society than a smaller paid force even when treasury payroll is low.

Demobilization is a transaction, not deletion. Settle survivors, dead, wounded, captive, missing, deserted, retained, equipment returned or lost, wages or arrears, route home, household status, labor return delay, reserve status, and political consequences. Local armed people return to local status; trained militia return to reserve; emergency levies return to their exact occupation or household when able. Repeated levies accumulate exhaustion and reduce later response.

## Provincial military scaling

Unmaterialized population contributes regional household arms, militia reserve, levy capacity, and follower capacity through compact province ledgers. This allows empire-scale rebellions and wars without creating thousands of unnecessary detailed unit owners. Permanent units materialize at the resolution required by causal importance. Active formations are created only for actual marches, battles, sieges, escorts, or other operations and dissolve when that operational arrangement ends; any required causal receipt remains load-on-demand rather than becoming a duplicate formation owner.

Standard kit stock limits standardized formations, not the number of people who can appear. Household and improvised weapons create lower-quality groups with exact penalties. Workshops may convert agricultural tools and raw materials over time; this consumes tools, iron, wood, labor, and production capacity and cannot instantly equip a province.

## population and economic resolution

Recruitment draws from conserved stratified population, occupation, prior-service, health, and potential pools. Detailed player recruitment reserves exact candidates and creates stable personnel IDs; NPC recruitment records aggregate intake, losses, resources, and completion windows. Active markets and projects use exact transactions; distant markets and projects use scheduled commodity or milestone state. No aggregate resolution relaxes cash, food, labor, equipment, transport, or political cost.

## economic-resolution fairness

Detailed and distant economies consume the same labor, land, seed, tools, animals, transport, security, stock, time, and money. Batch closes process the complete unprocessed interval. Aggregate state cannot hide costs, create stock, avoid spoilage, or bypass labor loss.

## Event-driven settlement processing
Settlements and projects store next material events and interruption triggers. Routine unchanged intervals are advanced in batches. Candidate pools, manpower ceilings, market views, and project forecasts are generated only when required and cached only by input digest.

## annual demographic close

A demographic close processes births, ordinary deaths, disease deaths, migration, military deaths, permanent disability, service transfers, returnees, and labor reassignment once for the covered interval. Every person remains in exactly one conserved population or service owner. Recruitment reduces an exact source group; discharge, desertion, return, capture, and death transfer or close that provenance.

Candidate snapshots are generated only when a recruitment campaign begins. The snapshot is determined by current demographics, occupation, age, health, prior experience, existing reservations, terms, local willingness, screening, and authority. Its input digest freezes that pool for the campaign. Screening selects from existing potential and capability; it never generates or rerolls potential.

## disease close

Disease spread uses current infectious cases, susceptible population, reproduction pressure, sanitation, quarantine, treatment capacity, illness duration, severe fraction, and treated versus untreated fatality. Each close records new cases, recoveries, deaths, and the control factor. Deaths and labor loss propagate to demographics, households, institutions, projects, formations, and revenue through the dirty-owner graph.

## world-close-contracts

Every materialized settlement and province owns a process contract with last processing, next review, inputs, interruptions, and processor route. Settlement closes reconcile food, production, imports, consumption, spoilage, population, births, ordinary deaths, migration, disease, labor, recruitment, service transfers, security, crime, occupation, loyalty, taxation, route access, institutions, markets, and projects.

Province closes conserve population and aggregate unmaterialized capacity. A monthly close handles stable economic and security state; births, long-run mortality, and demographic restructuring settle at appropriate annual or event-driven intervals. War, famine, epidemic, levy, migration, route failure, occupation, or direct interaction interrupts the batch.
