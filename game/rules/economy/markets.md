# Economy Module: Markets

## Prices and taxation

Prices use `game/rules/economy/markets.md#market-transaction`. Settlement scarcity changes with stock, consumption, expected deliveries, blockade, harvest, refugees, army presence, and hoarding.

## market-transaction

A market transaction requires exact buyer funds, seller stock, available quantity, price inputs, transport, legality, and time. Commit money and stock atomically.

## executable market price and transaction

Scarcity is calculated by `game/data/mechanics/economy.json`; zero current stock is handled by its explicit unavailable-market rule.

Unit price is calculated by `game/data/mechanics/economy.json`.

A transaction requires authority or voluntary consent, available stock, compatible payment, and transport capacity. It mutates buyer cash, seller cash, market stock, and buyer custody in one atomic transaction. Forecasts and valuations never mutate those owners.

## market-close-contracts

Every active or warm market owns an aggregate basket contract with settlement, depth, availability bands, price pressure, restock basis, route and security refs, last processing, next review, and interruptions. Basket state never creates exact stock. Merchant and depot lots materialize only through conserved sources and persist after access.



## Strategic material merchant convoys

Routine commerce remains aggregate. When an exact merchant house has sufficient conserved capital, one market has meaningful stock above its retained reserve, another reachable market has a material shortage, and diplomacy/routes permit trade, the runtime may materialize one exact aggregate merchant convoy. Dispatch removes exact cargo from the source market and purchase silver from merchant capital; the cargo exists only in the convoy while in transit. On arrival the destination economy pays only for cargo it can afford, purchased stock enters the destination market, and unsold remainder stays exact convoy cargo. This layer never creates one object per wagon or merchant and never duplicates routine aggregate trade.

Materialized convoys are physically disruptable. Live route/crossing damage forces rerouting from the last reached route node or a real delay. A controlled exact formation may attach as an escort only while co-located and mobilized; it remains its own formation owner, consumes its own field supply while traveling on the convoy chronology, and can suffer real losses. Interdiction requires an exact hostile formation inside the convoy's route-node time window. Cargo may be seized into that formation's exact captured-cargo ledger or destroyed, guard casualties debit the existing mercenary ecology, and a failed interception causes physical delay instead of abstract risk points.
