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

## aggregate intermarket trade

Routine intermarket commerce remains aggregate. Market stock, private-economy commodity ownership, aggregate private-economy cash/commodity ownership, route condition, diplomacy, scarcity, and local security determine lawful trade and restocking. No separate merchant NPC, merchant-house capital owner, or merchant-convoy gameplay owner is created for routine commerce. Named traders are materialized only when an individually relevant story interaction explicitly requires a person.

Player-relevant military transport uses exact formation movement plus detached shipment/convoy owners only when cargo physically separates from its army, together with depot, route, crossing, and logistics authorities. Routine baggage remains part of the moving formation/army and never creates a persistent army-train owner.
