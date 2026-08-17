# World Representation and Geography Overhaul

This change is an in-place migration of the clean rebaseline campaign. It does not reset campaign state, advance campaign time, or replace exact manpower/economic owners.

## Authority model

- Static location identity, containment, strategic-node classification: `game/data/world/locations.json`.
- Strategic and local route identity: `game/data/world/routes.json`.
- Travel weighting: `game/data/mechanics/travel-geography.json`.
- Persistent route status/control disruption: `state/territory/control.json#route_states`.
- Exact national/local population: `state/population/*.json`.
- Exact military/private/institutional manpower: existing `state/forces/*.json` owners.
- Military geography: force-owner-local `available_by_location`, cohort reserve geography, and formation allocation; these are partitions of exact force owners, never second owners.
- Exact mercenary bodies: individual mercenary company owners. Contract and registry records own zero bodies.
- Exact mounts: existing mount pool owners; regional reserve plus formation allocation is a conserved partition.
- Fortification blueprint: `game/data/world/fortification-profiles.json`.
- Materialized persistent fortification state: `state/fortifications/*`; static blueprints never overwrite materialized damage.
- Tang Manor siege inventory remains its own exact inventory and is linked to the enclosing Tang Manor fortified site.
- Repository and runtime routing are recorded in `runtime/contracts/repository-map.json`.

`game/data/mechanics/world-representation-authority.json` and `state/index/military-owner-classification.json` make body-owning and zero-body layers explicit.

## Geography hierarchy

Locations now distinguish state/polity, major region, settlement/fortress/pass, estate/compound, and facility/access layers. Facilities inherit containment but do not become demographic peers of their parent settlement or region.

National/local population allocation is restricted to legitimate demographic owners. Offices, halls, training grounds, gates, and depots no longer receive province-scale civilian or agricultural populations. Local economy follows the same demographic anchors.

## Route topology

Strategic routes connect strategic nodes only. Local routes connect gates, compounds, and facilities. External movement therefore reaches a settlement/fortress/estate access point before internal facilities.

The runtime uses the same graph for travel, formations, courier-style movement, and supply-route validation. Legacy route names are aliases, not competing geography owners. Institutional/contact routing IDs remain separate namespaces and are explicitly marked non-geographic.

Travel is deterministic and mode-aware. Current factors distinguish foot, mounted courier, formation, and convoy movement while preserving abstract game-scale duration rather than fake historical precision.

## Tang Manor, Kanyou, and Kankoku

Tang Manor is a fortified private estate in the Qin Capital Basin with an explicit outer strategic access gate and internal local routes.

Kankoku Pass and Kanyou are directly connected by the strategic route `route_kanyou_kankoku`. Tang Manor is a branch from the capital-basin network, not a mandatory node on the Kankoku-Kanyou trunk. Closing the direct Kanyou-Tang road does not magically isolate the Manor because a secondary capital-basin approach exists; both approaches must be unavailable to isolate it through the current strategic graph.

Kankoku's chokepoint behavior is tied to exact controlled route refs, terrain, fortification blueprint, controller, and persistent route state. It is not hard-coded as universally blocking all invasion.

## Seven State military geography

Exact state force headcounts are unchanged. Available bodies/equipment are partitioned across capitals, legitimate regional reserves, frontier regions, forts, passes, depots, and current formation locations. These geographic partitions remain subordinate to the exact state force owner.

State mount pools now have conserved regional reserve/disposition plus formation allocation. Moving a formation does not create or teleport replacement mounts.

## Private, personal, institutional, and mercenary forces

House/private forces have meaningful home/current geography without becoming state-owned. Tang Wei's personal force remains a separate exact owner; Qin troops under command remain Qin-owned.

Sword Manor remains exact institutional manpower. Geography does not convert its entire institutional population into free field troops.

Mercenary companies remain their own exact body owners. House Tang's defense contract is a zero-body agreement referencing exact company owners. The regional mercenary registry is explicitly authority:false and cannot be counted as another army.

## Minor polities and readiness

Ryouyou and the Quanrong highlands are represented in physical geography. Current Quanrong readiness/capability data does not contain an exact conserved population or troop count, so this migration deliberately does not manufacture one from `warband_capacity` or `muster_readiness` scores. Those remain readiness/capability, not bodies.

No exact living Jo polity exists in the clean source, so Jo remains unmaterialized rather than being invented from discussion or cold references.

## Fortification containment and occupation

Child facilities inside a fortified parent inherit the fact that they are behind that perimeter without duplicating wall state. Hostile transit may reach an external gate/access node but cannot use a local interior edge to teleport behind a hostile enclosing fortification.

Capture/occupation changes political/physical access only through the exact territorial and route-control relationships that apply. It does not duplicate native population, transfer legal claim automatically, or imply that taking an outer access point takes every interior facility.

## Bounded reads and performance

Play context exposes only bounded static map context for Wei's current location and immediate containment/access relationships. Hidden enemy disposition, garrison strength, route safety, and stockpiles are not exposed by static geography.

Indexes remain `authority:false`; transport/page limits are not world caps. Runtime routing uses owner-local/location-local data rather than adding a new whole-world mutable authority.

## Migration and validation

Migration provenance is recorded in `state/migrations/world-geography-overhaul-v1.json`.

Focused invariants cover:

- population and local-economy demographic ownership;
- location hierarchy and cycle detection;
- strategic versus local route endpoints;
- route aliases and persistent route state;
- border and chokepoint relationships;
- state force and equipment disposition conservation;
- mount conservation;
- mercenary contract non-duplication;
- capability profile source-owner semantics;
- Tang Manor fortification/inventory containment;
- Kankoku route control;
- operation reference integrity;
- repository routing;
- player-safe map context.

## Intentional remaining limits

1. Quanrong/Ryouyou has no exact current population/army headcount authority in the clean source. The map is live; the troop total remains intentionally unmaterialized until lawful source data or gameplay establishes conserved bodies.
2. Jo has no exact living current owner and therefore remains cold/unmaterialized.
3. Some regional mercenary companies had no finer historical home-settlement provenance in the clean source; they were given conservative regional geographic anchors rather than fabricated detailed histories.
4. The clean source keeps Tang Manor civilian/support population and House/Sword exact military ledgers as separate authorities without complete retrospective individual ancestry for all pre-existing private military bodies. This migration did not invent a historical population transfer solely to fill that provenance gap.
