# Siege, Artillery, and River Operations

`data/mechanics/siege.json` is the sole numerical authority for artillery crews, engineering factors, access, cycle time, range, scatter, penetration/impact, structure protection, integrity loss, stone-drop and firepot resolution. `data/mechanics/combat.json`, `data/mechanics/injury.json`, and the item catalog resolve people, weapons, animals and wounds.

This file defines the causal state and legality of siege and river operations. It does not duplicate the structured numerical tables.

## Full siege state

A full siege tracks:

- fortification sectors, gates, walls and towers;
- attacker/defender camps;
- food, water, fodder and disease;
- civilians and loyalty;
- repairs;
- artillery and ammunition;
- mining and countermining;
- fire;
- assaults and sorties;
- negotiation and surrender;
- relief forces;
- withdrawal, occupation, prisoners and aftermath.

River mechanics cover transport, ferries, crossings, temporary bridging and river logistics. No naval-warship capability is created without a registered subsystem.

## Crew and operation legality

An artillery or engineering method is illegal when the exact current fit crew, specialists, access, ammunition, tools, workspace or physical geometry fail its registered minimum.

Qualification is a procedure gate. It does not multiply a stored skill twice.

One person cannot simultaneously crew two weapons, fight on the wall, repair a breach and rest. Duty allocations are exclusive over the same time interval.

## Artillery release contract

Every consequential release records:

- weapon/emplacement ID;
- exact crew and specialists;
- commander;
- start/release time;
- condition;
- fatigue;
- ammunition before/after;
- target and geometry;
- range/elevation;
- visibility, wind and precipitation;
- control inputs;
- deterministic scatter seed;
- impact/landing coordinate;
- contact grade;
- casualties and structural damage;
- equipment damage;
- crew fatigue;
- condition loss;
- next-ready time.

Missing required inputs block the release rather than inviting estimation.

## Deterministic scatter

Scatter uses the registered SHA-256 deterministic method in `data/mechanics/siege.json`. Reloading, reopening the chat, or disliking a result cannot reroll the same release.

## Bed crossbows

Bed crossbow crew, cycle, range, dispersion and penetration come from `data/mechanics/siege.json` and the registered item/ammunition profiles.

The shot travels through actual geometry in order. It may continue through contacted layers only while registered remaining penetration permits it. People, shields, armor, horses, structures and equipment are counted once.

## Trebuchets

Trebuchet crew, cycle, range, dispersion, projectile mass and impact come from the structured siege registry.

A landing on empty ground causes no invented casualties. Debris effects require actual nearby people/objects and registered structure interaction.

## Stone-drop and firepot systems

Stone-drop attacks require the target to occupy a valid footprint below the release point and require a clear drop path.

Firepots consume actual prepared ammunition. Ignition uses the structured score and deterministic resolution. Burning cells store footprint, fuel, duration, smoke, spread edges, exposed people/animals/structures and suppression work.

## Structures and breaches

Structure protection and integrity are calculated from actual material resistance, thickness, condition, angle and impact. Integrity state follows `data/mechanics/siege.json`.

A wall cannot be crossed by equipment that physically cannot reach it. An attacker must use a legal gate action, breach, mining, ramp/custom project, infiltration, negotiation, surrender or another registered method.

## Fatigue and relief

Artillery, mining, repair, assault, hauling and fire response consume time and fatigue. Long operations require shifts, food, water and rest. A long bombardment cannot end with unchanged fatigue unless actual relief/recovery state supports it.

## Tang Manor siege doctrine

Tang Manor geometry, walls, moat, gate complex, Inner Citadel, artillery, ammunition, repair stock, food, water, medical capacity and defenders remain separate authoritative inputs. No claim such as "impossible to conquer" replaces calculation.

Outer contracted companies perform the duties saved in their assignments. House Guards, Guardian Cavalry and Sword Manor use their saved defensive/relief roles. This doctrine changes deployment, not physical invulnerability.

Tang horse/equipment secrecy does not make captured material disappear. Battlefield capture/loss creates real recovery, denial, intelligence and security consequences.

## River movement

River crossings and transport require actual boats/rafts/ferries/bridges, capacity, loading/unloading time, current/weather, route security and receiving space. People, animals and cargo are conserved across the crossing.
