# Loadouts, Institutional Equipment, and Forge

`game/data/loadouts.json` is the sole structured authority for loadout contents. `game/data/items.json` owns item-pattern mechanics. Equipment state stores custody, count, condition, ammunition, mount, issue status, and location. A rulebook or character record may reference a loadout but may not recreate its contents as a competing authority.

## Loadout legality

A loadout is usable only when its required items, ammunition, mount, tack, armor, tools, and containers are physically available to the owner and any size/fit requirements are satisfied. Issue transfers custody or authorized use. Return, loss, capture, breakage, consumption, and replacement update the actual stock owners.

Changing a loadout is a real action whenever it requires retrieving, donning, removing, packing, saddling, distributing, or exchanging equipment. Equipment does not teleport between depot and user.

## Institutional issue

State armies, mercenary companies, schools, escort houses, House Tang, Sword Manor, and other institutions retain their own stock ownership. Assignment under another commander does not silently transfer institutional ownership.

A unit's standard does not guarantee every member has a complete set after loss, shortage, capture, wear, or delayed resupply. Current issue state controls.

## House Tang

House Tang restricted equipment remains available only through current House authority and existing stock/production. Current personnel counts and current issued loadouts are read from owner state. Role/loadout doctrine may constrain what a qualified role normally uses, but this rule file never fixes how many such people currently exist.

## Forge and maintenance

Production and repair require a registered pattern, facility/workstation capacity, labor, craft capability, tools, material, time, supervision, and stock destination. Training/facility factors use `game/data/mechanics/training.json`; procurement, maintenance reserve, and repair-slot arithmetic use `game/data/mechanics/economy.json`.

Forge output never creates an unregistered mechanical improvement. A changed design must become a registered item pattern before production.

## Deterministic precedence

`game/data/loadouts.json` controls contents. `game/data/items.json` controls physical patterns. Structured mechanics registries control numerical effects. This file owns issue, custody, fit, production, and institutional-equipment semantics only.

Loadout lookup uses `game/data/loadouts.json` as a small ID-to-shard index. Load only the referenced shard for ordinary play; the index is authority for location, while the shard owns the definition.

Item lookup uses `game/data/items.json` as a small ID-to-shard index. Load only the referenced item shard during ordinary play.
