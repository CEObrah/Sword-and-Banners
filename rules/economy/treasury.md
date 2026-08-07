# Economy Module: Treasury

## Revenue, expenditure, taxation, and treasury settlement

Every institution, settlement, estate, company, and army uses one authoritative treasury or referenced account. A review records opening balance; realized income; wages; rations; fodder; maintenance; purchases; debt service; taxes; gifts; losses; reserved funds; and closing balance.

Closing balance is calculated by `data/mechanics/economy.json`.

Unpaid obligations become exact arrears and enter institutional pressure. Expected income is not cash. Taxes assessed are not taxes collected. Loot valued is not loot sold.

Tax assessment depends on population, land, trade, offices, exemptions, records, and policy. Collection is capped by assessed liability, collectible wealth, collector capacity, route security, and compliance or coercive reach. Overcollection transfers real household stock or money and may reduce next-cycle production, seed, loyalty, and population.

## Economic resource separation

Cash, edible stock, fodder, animals, equipment, raw material, labor, legal claims, and credit are separate owners. A silver-equivalent valuation is for comparison only and never permits an automatic conversion.

A monthly account therefore closes five ledgers:

1. cash received, paid, reserved, owed, and borrowed;
2. food person-days produced, stored, consumed, spoiled, seized, bought, and sold;
3. fodder horse-days and animal movements;
4. durable equipment, ammunition, raw material, vehicles, and facilities by condition;
5. labor-days, service obligations, households affected, and population transfers.

In-kind revenue offsets only compatible physical demand. Grain cannot pay a smith who requires silver; tax silver cannot feed an isolated army until a purchase and delivery occur; credit is not income and creates a future claim.

## Revenue-source ledger

Every expected income has one source record containing owner, legal or coercive basis, payer or producing property, resource type, gross amount, production or assessment period, due date, collection agent, route, security, compliance, loss, restrictions, and realized amount.

Revenue classes:

- recurring: wages, office stipend, rents, market fees, tolls, ordinary taxes, subscriptions;
- seasonal: harvest tax, estate surplus, livestock, horse or timber sales;
- contractual: escort, garrison, campaign, training, construction, transport;
- commercial: trade, workshops, ferries, warehouses, mills, shipping;
- political: patronage, tribute, state transfer, allied contribution;
- one-time: loot allocation, ransom, lawful confiscation, asset sale;
- emergency: extraordinary tax, requisition, forced loan;
- deferred finance: loan, supplier credit, arrears, land grant, tax assignment.

Loans, arrears, requisitions, and asset sales are never counted as recurring operating income.

Realized cash revenue is calculated by `data/mechanics/economy.json`.

Use supported factors 0.25, 0.50, 0.75, 1.00, or 1.10. Fractional silver carries forward. In-kind collection uses the same procedure but transfers exact goods instead of money.

## Revenue methods and consequences

An army may be supported through official employment, military contracts, patronage, estates, military farms, trade, workshops, market or ferry rights, taxation, tribute, allied contingents, loot, ransom, lawful fines, loans, land grants, or tax assignments. Each route needs actual access and creates different dependencies.

- Employment and contracts define who owns the troops, who pays, what stock is supplied, and what happens on failure.
- Patronage provides rapid capacity but creates obligation, influence, and possible loss of independence.
- Estates and workshops require land, labor, inputs, management, security, maintenance, storage, and buyers.
- Trade requires working capital, cargo, transport, guards, route access, time, market depth, and a buyer.
- Tolls and fees require lawful or coercive control of an active route; excessive charges reduce traffic and increase evasion.
- Taxation requires assessable wealth, records, collectors, route security, compliance, and political tolerance.
- Loot and ransom are uncertain one-time receipts and may carry allocation, misconduct, legality, and retaliation consequences.
- Loans advance liquidity but add interest, collateral, due dates, and default risk.
- Land grants and tax assignments reduce immediate cash burden while transferring durable economic and political power.

## Monthly institutional close
At each owner's crossed monthly close, perform once in this order:

2. settle labor availability, production, harvests, workshops, estates, and facility condition;
3. consume civilian and military food, fodder, water, fuel, ammunition, medicine, and maintenance inputs;
4. assess taxes, rents, fees, tribute, contracts, and other due revenue;
5. realize only resources that can legally and physically reach the owner through a valid payer, collector, route, convoy, and receiving capacity;
6. settle payroll, family support, suppliers, facilities, debt, compensation, recruitment, training, and demobilization;
7. post unpaid obligations and undelivered in-kind support as arrears or shortages;
9. close cash, food, fodder, material, labor, receivable, and debt ledgers independently;
10. recompute runway and sustainable-force ceilings and schedule the next close or earlier crisis threshold.

## Generated financial views
Payroll, formation burden, revenue projection, runway, and deficit are derived views keyed by input digest. Treasury owners store current balances, receivables, arrears, debt, reserves, recurring sources, and exact transactions only. Cold treasuries use lazy accrual until access, a rate change, a required close, or a material threshold.

## treasury-close-contracts

Every treasury owns or explicitly inherits a close contract covering realized income, in-kind support, payroll, upkeep, debt, arrears, procurement, projects, transfers, seizure, and authority. Expected income is not cash. Monthly batching is allowed only when rates and dependencies stayed stable; otherwise split at each material change.

## universal-resource-state-lifecycle

Every physical or financial resource may be `available`, `reserved`, `issued`, `in_transit`, `consumed`, `damaged`, `lost`, `captured`, `under_repair`, `returned`, `transferred`, or `destroyed`. Incompatible states are invalid.

Reservation occurs before commitment and prevents overlapping use. Assessed value, credit, receivable, stock, labor, and cash remain separate until a real transaction converts them.




Resource owners store current stocks, contracts, custody, and scheduled reviews. A close records opening stock, actual additions, deductions, loss, closing stock, custody, and the successor review. Baseline flows are forecasts only. Campaigning, siege, blockade, damage, unpaid labor, disease, weather, route failure, and market disruption split or reduce realization.

If play crossed a review boundary without writing its close, Checkpoint may settle it only from saved production, labor, stock, contracts, routes, security, prices, consumption, and interruptions. Missing causal support produces no automatic gain and must remain blocked or conservatively unchanged. Audit never fabricates resources.
