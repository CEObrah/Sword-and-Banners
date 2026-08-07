# Organization and Unit Law

## Core hierarchy

`person / unorganized manpower -> homogeneous unit -> command group -> formation -> army / operation / institution`.

A **unit** is the only persistent aggregate mass-combat organization. A unit has one troop type and one intended organizational standard loadout. It owns headcount, aggregate capability, doctrine, training, tendencies, cohesion, morale, readiness, condition, experience/history, home chain, current assignment and equipment issue state. Large ordinary units resolve from aggregate statistics under `data/mechanics/unit-resolution.json`; never create one character sheet per ordinary soldier.

A **commander** is a separate person who may command multiple units or subordinate command nodes. A **formation** is a temporary operational/battle arrangement of units and owns no manpower. A force pool is accounting-only manpower and cannot fight until allocated to units.

## Hard unit boundary

One unit means one troop type and one intended standard loadout. If only a subset should receive a different durable loadout, doctrine, training plan, commander, mount standard, assignment or other persistent standard, `SPLIT UNIT` first. Example: re-equipping 1,000 men inside a 5,000-infantry unit produces a 4,000-infantry unit retaining the old standard and a 1,000-infantry unit beginning the new refit. Infantry and archers never share a unit.

Split/merge is a canonical transaction governed by `data/mechanics/unit-partition.json`. Neutral splits preserve the parent represented capability distribution; integer categories use deterministic largest-remainder allocation. Explicitly concentrating veterans, specialists, stronger members, better equipment, or other quality requires a real selection/reallocation action with criteria, authority, evidence and time. Conserve people, named-member claims, horses/animals, weapons, armor, ammunition, supplies, injuries, fatigue, experience, morale/cohesion inputs and history. Do not silently select superior soldiers into a child without an explicit lawful selection action. Compatible same-type units may merge only after standards are reconciled; continuous capabilities use personnel-weighted pooled moments, integer categories sum exactly, and integration can reduce cohesion/familiarity until real training/time restores it. Split/merge invalidates and rebuilds derived battle kernels.

`SET LOADOUT` changes the target standard for the whole unit. It does not instantly create equipment. Refit consumes real stock, transport, fitting/maintenance, ammunition, mounts where relevant, familiarization and time. Temporary shortages/damage/substitutes are issue/readiness state, not a second standard. Named exact/individual-lite members may retain personal equipment exceptions.

## Command hierarchy

Use `data/mechanics/command.json`. Every commander has one ownership-agnostic direct budget with two axes: direct personnel and direct command slots. Personal, assigned, attached, institutional and mercenary units share the same limits. A direct leaf unit costs one slot. A subordinate command node costs one slot. Delegated whole units stop counting against the superior direct personnel/leaf-unit load and count against the subordinate instead; the superior retains one subordinate-node slot. Recursive strategic authority is not direct control.

Thus a commander comfortable at 10,000 personnel / 8 slots who has 15,000 in 10 units can delegate 5,000 in 4 units to a subordinate. The superior then carries 10,000 direct personnel plus six leaf-unit slots and one subordinate-command slot; the subordinate carries 5,000 plus four units.

Splitting never grants free power: additional directly controlled units increase span burden and do not create frontage, actions or combat multipliers. Effective capacity is deterministic: interpolate the commander rating anchors, apply only evidence-supported health/staff/doctrine/terrain/information modifiers from `data/mechanics/command.json`, then compute `load_ratio = max(direct_personnel/effective_personnel_capacity, direct_slots/effective_slot_capacity)`. The saved state therefore produces the same command-delay/synchronization consequences every time. Staff/signals, doctrine familiarity, terrain/dispersion, information quality, health and fatigue affect command/control rather than soldiers permanent attributes.

## Ownership, attachment, return

Temporary command never changes ownership. Intact assigned units retain their source owner, home establishment, identity, history, doctrine identity and equipment custody unless lawfully transferred. Raw personnel entrusted for player organization may be formed into legal same-type units within granted authority.

Returning troops restores the surviving force to its home organizational chain, not its old condition. Casualties, injuries, experience, lawful promotions, morale/cohesion changes, equipment/horse losses and history persist. The owner reconstitutes with real replacement manpower, officers, stock, horses, training and time.

## Support and camp followers

Use `data/mechanics/support.json`. Medical, logistics and signal units are real military service-support units and can be moved, disrupted, defended and suffer casualties, but they do not automatically add offensive line frontage. Engineers/scouts contribute their specialist capacity unless deliberately committed. Civilian camp followers/dependents/laborers are noncombat populations, not military units; armed train guards are separate homogeneous guard units.

## Formation and large battle

Formation templates describe arrangements a force knows; active formations exist only for real operations. Formations reference units and own no manpower. Large battles resolve ordinary units as aggregate statistical actors. Materially equivalent units may be vectorized for computation only, with every result settled to actual unit IDs. Wake full capability for close thresholds, specialist actions, unusual terrain/equipment, named actors or any asymmetry that can change the outcome.

## Player agency

World-owned forces have their normal home establishment. Tang Wei's unorganized personal retinue remains `permanent_units: []` until the player creates units. OOC/preview discussion never creates organization or intent.

## Command groups as direct elements

A **command group** is a persistent/operational command-only node, not a troop unit. It owns no manpower. It points to one real commander person, zero or more directly controlled homogeneous units, optional directly controlled named people, and zero or more subordinate command groups. Its authoritative state lives under `state/cmd/command-groups/` only after an actual appointment/delegation creates it.

For span-of-command, a superior's direct elements are **direct troop units + direct subordinate command groups**. Example: `Archer Unit`, `Infantry Unit`, `Mercenary Unit`, and `Jang Command` consume four direct slots. The units nested under `Jang Command` do not also consume the superior's direct slots or personnel budget; they consume Jang's. The superior still retains recursive strategic authority where the appointment/order grants it.

The commander of a command group remains a real combat-capable person. If present, that person can move, fight, use personal equipment/techniques, be wounded, killed, captured, isolated, exhausted, or routed. Personal combat never gets averaged into the unit's ordinary-soldier capability. Command loss triggers deputy/succession/standing-doctrine handling; directly absorbing orphaned child units increases the superior's direct load immediately.
