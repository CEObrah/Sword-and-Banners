# Items and Stock

`game/data/items.json` is the sole structured authority for ordinary item patterns, including mass, dimensions, physical profile, durability, baseline value, ammunition, armor, mounts, tack, tools, vehicles, siege equipment, and other catalog properties. Any unique or named item must resolve to one registered item pattern in `game/data/items.json` plus explicit instance state.

## One physical definition

Mechanically identical items share one catalog pattern. An inventory, character, formation, institution, or scene may reference a pattern and store instance-specific custody, quantity, condition, ammunition state, modification, damage, and location. It may not redefine the pattern's base mechanics inline.

If an item differs mechanically in material, size, construction, draw weight, armor coverage, mount training, vehicle capacity, or another consequential property, it requires a distinct registered pattern before consequential use.

## Custody and conservation

Items are conserved. Purchase, issue, capture, loss, destruction, repair, consumption, ammunition expenditure, transfer, caching, abandonment, and recovery change exact owners or quantities. A described weapon or horse that is not in a valid owner or scene record is not available merely because it would be convenient.

Ammunition is conserved at the finest active resolution appropriate to the scene. Named individuals use exact projectiles or containers; small units may use exact bundles and remainder; large formations may retain exact total ammunition with derived volley equivalents.

## Condition

Item condition-state thresholds and combat consequences are defined in `game/data/mechanics/combat.json`. Armor trauma and structural failure use `game/data/mechanics/injury.json` and `game/data/mechanics/combat.json`. Repair consumes real time, labor, tools, material, access, and money through the registered economy/equipment process.

## Prices

Exact item-pattern baseline values are in `game/data/items.json`. Ordinary reference-basket wages, rations, and prices are in `game/data/mechanics/economy.json`. A transaction may use a different local price only when the market inputs and resulting exact price are saved before money and stock transfer.

## Combat use

Weapon timing, reach, contact, ranged behavior, mounted compatibility, encumbrance, fatigue, structural wear, armor interaction, and injuries are resolved by the structured combat/body/injury registries. Narrative descriptions never add reach, force, penetration, armor, ammunition, hands, or special abilities not present in the registered pattern and current state.

## Tang restricted equipment

Tang-exclusive patterns remain restricted by House Tang policy and custody. No sale, gift, stud service, blueprint transfer, production access, or outside issue occurs without an explicit lawful House transaction. Capture or theft can still transfer physical custody and must trigger the resulting security process.

## Deterministic precedence

For calculations, structured item and mechanics registries control. This file defines inventory semantics, conservation, and legality only.

Item lookup uses `game/data/items.json` as a small ID-to-shard index. Load only the referenced item shard during ordinary play.
