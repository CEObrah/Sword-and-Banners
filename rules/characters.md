# Character Model and Materialization

`data/mechanics/economy.json` owns procurement and maintenance arithmetic used by character/equipment settlement.


Exact characters use physical and social state plus a narrative profile: core traits, values, speech pattern, behavioral tell, conflict style, current objective, concealed concern, knowledge boundary, and relationship posture. Materialization must reconcile source unit, age, health, role, equipment, location, and prior settled history without canon bonuses.




skill_order: Sword, Spear, Glaive, Axe, Mace, Staff, Dagger, Bow, Crossbow, Shield, Defense, Athletics, Mass Combat, Grappling, Unarmed, Riding, Formation Fighting, Survival, Stealth, Scouting, Navigation, Medicine, Engineering, Leadership, Formation Command, Tactics, Strategy, Logistics, Intelligence Operations, Training, Diplomacy, Law, Trade, Intrigue, Governance

## Universal character kernel

Every persistent person uses the same underlying model: identity, source population, generation seed and schema, age, sex, body, health, nine attributes, nonzero or relevant skills, specializations, aptitude, potential, certification, combat experience, readiness, injuries, loadout, service history, and development evidence.

Attribute order for compact personnel arrays:

`Strength, Agility, Endurance, Toughness, Coordination, Awareness, Composure, Intelligence, Presence`.

Compact exact-character skill-array order:

`Sword, Spear, Glaive, Axe, Mace, Staff, Dagger, Bow, Crossbow, Shield, Defense, Athletics, Mass Combat, Grappling, Unarmed, Riding, Formation Fighting, Survival, Stealth, Scouting, Navigation, Medicine, Engineering, Leadership, Formation Command, Tactics, Strategy, Logistics, Intelligence Operations, Training, Diplomacy, Law, Trade, Intrigue, Governance`.

Omitted skills are untrained unless a profile explicitly supplies a baseline. Tang Wei, full-sheet NPCs, named units, unit means, and materialized officers use the same scales and checks.

## Resolution levels

- Population distribution: aggregate civil/population accounting before exact people are materialized.
- Unit: the only persistent aggregate military organization; one troop type with one standard loadout. Equivalent units may be computed together without creating another state owner.
- Featured character: full independent agency, relationships, knowledge, goals, and narrative memory.
- Player character: same mechanical model with player-controlled choices.

Resolution level never grants capability, survival, growth, equipment, knowledge, or plot protection.
## Capability scale

- ordinary adult: 25-45;
- conditioned worker or militia: 35-55;
- professional soldier: 45-70 attributes and 40-70 primary skills;
- veteran: 60-85 attributes and 70-95 primary skills;
- elite officer or guard: 75-100 attributes and 90-115 decisive skills;
- Kingdom-scale hero: 100-150 in decisive domains;
- Dynasty Warriors-scale hero: above 150 in decisive domains, supported by Mass Combat, body, endurance, equipment, geometry, and present condition.

Scores remain uncapped. No number creates magic, immunity, teleportation, or simultaneous presence in several sectors.

## Age, adulthood, and service eligibility

Age 16 is ordinary adult eligibility and the minimum ordinary state conscription age. Voluntary House Tang battlefield service may begin at age 10 under direct family authorization, a full-sheet adult protector, exact age-appropriate equipment, health, and capability checks. Ages 10-15 receive no adult civil authority, independent command, contractual capacity, or physical capability by age alone.

Character height, wingspan, arm span, body radius, personal reach, and body-growth measurements are not game fields. Combat reach comes only from the current weapon or fixed combat-method pattern.

## Equipment condition, fit, and concrete craft
Generic crude/common/military/superior/masterwork/exceptional combat tiers are retired. Equipment capability comes from its actual pattern fields, current condition, fit, carriage, and any explicitly named physical craft trait.

A craft trait is not a prestige label. It must alter exactly recorded fields, such as reduced mass, improved balance/handling, increased structural capacity, better fit, lower maintenance, or altered material resistance. The changed catalog or exact-item values enter ordinary formulas once. Decorative workmanship, famous ownership, or price does not create combat power.

Condition and fit use `rules/battle.md#condition-fit-and-craft`. Exact consequential items may store continuous condition. Aggregate stocks use condition-band quantities.
## Catalog economic fields
Every physical pattern has a numeric `baseline_value_silver` for one sound reference item. Actual purchase, sale, manufacture, repair, and replacement use stock, market depth, scarcity, legality, bulk, materials, labor, craft capability, route, condition, and time.

Procurement value is calculated by `data/mechanics/economy.json`.

Concrete custom work costs the actual materials, skilled labor, tools, supervision, inspection, failure risk, and time needed to change a named field. Money alone cannot create a physical improvement that the workshop cannot produce.

Routine maintenance reserve is calculated by `data/mechanics/economy.json`.

Operating-mode maintenance factors are defined only in `data/mechanics/economy.json`. Maintenance is realized only when labor, tools, materials, access, and time are committed.
## Canonical position modifiers

`rules/combat.md`, `rules/combat.md`, `rules/combat.md`, and `rules/battle.md` own combat resolution. Catalog circumstances map only to the fixed positional levels in `data/mechanics/combat.json`; physically impossible reach, clearance, footing, perception, or method makes the action illegal rather than creating an unbounded modifier.

Examples: a small reach edge is minor; a stable flank is major; a genuinely undetected rear attack is decisive until detection; a prepared spear line is clear or major according to completed formation state; awkward but legal clearance is minor/clear; impossible minimum range is illegal. Fatigue and injuries normally act through usable values, not a second duplicate flat penalty.

## Stable and current ownership
Stable identity, body, attributes, skills, aptitude, potential, and service history live in the character owner. Current action, target, location within the hot scene, immediate knowledge use, and next decision live in `state/scene.json` and the referenced typed owner. Omitted skills equal zero.

## Development parity

All permanent development uses `rules/growth.md`. Name, player status, canon status, resolution tier, active loading, and narrative attention are not inputs.

## qualification-profile-routing

`qualification_personal_uncredentialed` owns no institutional authority; `qualification_scout_qualified`, `qualification_healer_advanced`, `qualification_guard_qualified`, `qualification_officer_qualified`, `qualification_elite_martial_advanced`, `qualification_civil_advanced`, and `qualification_commercial_qualified` record role legality only. They do not change attributes or skills. Exact sparse certifications may override a profile after a saved assessment.
## general-opposed-capability-routing
Opposed non-combat capability uses the same scale for player and NPC: relevant skill and specialization plus weighted attributes, legal equipment or records, position, information quality, health, fatigue, environmental conditions, and committed uncertainty. Development status, naming, canon status, and loaded state provide no bonus. Domain procedures in `rules/personal-force.md` determine evidence, detection, delay, and consequences.

## birth-date-and-age
Every already-born persistent person stores one exact `birth_date`. `age` is a validated checkpoint cache, not a second mutable truth. Future identities store no birth date before a causal birth. Life stage, adulthood, age-based law, maturation, and aging pressure derive from birth date plus world time through `rules/growth.md#birthday-and-age-authority`.

## compact-routed-maturation

The human kernel supports compact settlement for cold-active routed identities and aggregate populations. Age changes only at crossed birthdays. Childhood and adolescence process health, nutrition, coordination, endurance, language, education capacity, and age-appropriate labor or practice without generating an adult capability sheet.

Poor nutrition, illness, injury, displacement, excessive labor, unsafe training, missing guardians, and lack of instruction reduce or block development. Household wealth, rank, or canon status never grants fixed capability. Life-stage ceilings prevent infants and children from receiving adult training, command, office, or combat competence.

## authoritative-and-derived-character-fields

Birth date, current health, equipment custody, location, service, and appointments are authoritative facts. Age, life stage, current load ratio, authority display, remaining recovery time, and narrative status are derived. Rebuild them at startup, after affected transactions, and checkpoint.

A birthday creates no automatic attribute, skill, knowledge, rank, office, or authority. Age affects development and health only through the owned aging rules and actual evidence.

## Executable talent representation

A character owner may store universal domain aptitude and potential factors, but not prose-only dormant talents or promised future abilities. Current attributes, skills, specializations, qualifications, and experience must come from actual persisted evidence or later development receipts. Omitted skills remain zero.

## Compressed recurring exact profiles

Before the ordinary omitted-skill-equals-zero rule is applied, a compressed exact profile expands its stored template, immutable seed, accumulated unit receipts, age stage, health state, and explicit overrides. The expanded array is exact. A cold profile is not expanded merely for storage or audit display.



## Persistent-name rule

Anonymous aggregate people have no personal identity record. When a generated ordinary person is lawfully materialized as a persistent individual-lite person, assign one stable personal name and ID immediately and preserve them through any later exact-character promotion. Canonical cold-active routed identities retain their canonical name at every representation depth. Never delay a persistent individual's name until full-sheet promotion.

## Individual-lite combat sheet

An individual-lite owner is a persistent named person used when unit resolution is insufficient but a full narrative character is not justified. It keeps one stable ID, canonical display name, birth date, body, appearance, exact capability, aptitude, health, fatigue, equipment state or role-profile reference, location, assignment, combat/service history, compact personality when supported, important relationship references when supported, and current duty/goal when supported. It does not require a large biography or fabricated social depth. Promotion to a full exact character preserves the same identity and all existing mechanical/history state.

Anonymous ordinary people remain aggregate population/manpower state; armed organized personnel belong to units. Generated anonymous people receive a personal name only when lawful materialization creates a persistent individual; canonical routed identities retain their canonical name.

## Named owner and unit-aggregate separation

A named full-sheet character is one separate body owner. If that person was materialized from an aggregate unit, the unit headcount is deducted exactly once at materialization and the named person is thereafter tracked separately. Removing or killing the named person must never deduct the unit a second time. Deterministic aggregate casualty resolution excludes already-materialized named people.




## Runtime tiers

- Full exact character: complete independently simulated narrative/mechanical actor with exact body, capability, knowledge, relationships, goals and activity when causally required.
- Individual-lite person: persistent named individual with exact body/capability/equipment/service state and compact narrative state.
- Cold active routed identity: canonical named person represented through `state/char-roster/index.json` and its exact shard; it has a real world route/source but no fabricated exact capability/location/office until causally materialized.
- Aggregate person: ordinary population/manpower member represented only through a population, institution or unit owner.

Cold status is retrieval compression only. It never means the person does not exist, receives free progression, or is exempt from offscreen life/development parity.

## Separation of profile and runtime state

A full capability profile does not by itself assert a current location, health, inventory, office, travel, or personal review. Runtime facts must have an authoritative owner. Cold full profiles are not loaded or processed until a causal activation.

## Routed identity activation

A routed identity cannot act independently. Activation first resolves current existence, source unit, role template, age stage, location, health, authority, equipment, knowledge, and goal. `rules/characters.md` then constructs the exact profile and deducts one source owner slot. Missing inputs cause fail-closed nonactivation.

## Context routing

Startup loads no external profile shard. A lookup loads the compact router, one profile or identity shard, and the relevant runtime/process owner. Large scenes use deterministic sector, formation, authority, or owner batches sized to available context. Batch size may change; semantic coverage may not. No final result commits until all required batches reconcile.

## Anti-bloat invariants

- no alias arrays or duplicate normalized identity keys;
- no campaign-original exact quota filler;
- no generic random state, age, role, office, location, health, equipment, knowledge, goal, or elite skill;
- no cold personal periodic clocks;
- no full-array expansion for cold-active routed identities during save, time advance, or audit;
- no repeated attribute or skill order inside each individual record when a shard-level order owns it;
- no profile definition treated as a living runtime body without activation evidence.

## Ordinary-person naming
Units do not carry complete name lists. Exact names are materialized only through the mandatory triggers in `rules/agency.md`. Compact casualty and memorial records do not become active character sheets.


## canonical-name narration

Every full capability-profile identity, active exact external actor, and cold-active routed named identity retains one canonical display name. Whenever the identity is legitimately referenced, reported, encountered, or materialized, narration uses that canonical name. Cold status suppresses irrelevant loading, not the name.


## Initial-date projection safety

A cold full capability profile is a capability definition, not an automatic 245 BCE body state. On activation, reconstruct age-stage, affiliation, office, health, equipment, location, knowledge, relationships, and current capability through the source unit and explicit initial evidence. Future achievements, future ranks, and later-series peak values cannot be imported as initial facts.




## Scope

This module creates a recurring exact canonical actor or a full-sheet person from a real unit or routed identity. It never invents state affiliation, initial existence, age, role, location, office, equipment, knowledge, relationship, health, or authority from a random seed.

## Required inputs

- one identity or new-person ID;
- verified source population/unit owner and one deducted integer slot;
- resolved role template;
- age stage or exact age;
- unit development, occupation, health-exposure, and service receipts through the activation time;
- immutable profile seed;
- explicit canon or campaign evidence overrides;
- activation event and idempotency key.

No exact action occurs until all required inputs exist.

## Character materialization templates

Attribute order, skill order, role-template base values, signature skills, unspecified-skill base, deterministic seed variation, and generated-value clamps are defined only in `data/mechanics/career.json`. A template is a deterministic starting profile for a resolved role, not permission to invent identity, affiliation, equipment, location, history, or authority. Primary-weapon and verified-specialty placeholders must be resolved from saved evidence before materialization.

## Seed variation

Character materialization variation, hash input, delta ranges, and clamps are defined only in `data/mechanics/career.json`. The seed may vary capability only; it may not choose factual identity or world-state fields.

## Application order

1. Resolve identity, source unit, role, age, and activation boundary.
2. Deduct one source owner slot.
3. Apply role-template base values.
4. Apply seed variation.
5. Apply accumulated unit development, service, injury, aging, and health receipts exactly once.
6. Apply explicit evidence overrides last.
7. Create health, location, equipment, authority, knowledge, goal, activity, and successor-clock owners.
8. Validate no named/unit overlap and write the materialization receipt.

Failure at any step leaves the identity cold-active/routed and produces no acting exact character.


## personal-unit promotion

Named individual-lite personal-force members already retain their saved canonical names and IDs. Anonymous ordinary unit members have no complete name list. When a previously anonymous ordinary member is lawfully materialized as a persistent individual, deduct exactly one surviving unit member, assign one stable canonical name/ID using the registered deterministic materialization procedure, import settled unit history exactly once, and create no replacement body.


## body and appearance
Every exact or character-lite person has a birth date, derived age, adult height, growth profile to age 18, dynamic weight, frame, and appearance. Height and weight participate in personal combat physics. Mass units use distributions instead of individual body records. Named characters remain individuals even when commanding unit-based House or state troops.

Named military officers remain individual people even when operating with mass forces. Their command-unit attachment is separate from unit representation.


## Information-density rule

Exact characters do not require duplicated `character_profile` and `personality_signature` blobs, a minimum relationship count, or fabricated individuality. `behavior`, when present, is the compact character-specific narrative profile. Existing bespoke behavior outranks generic generated filler. Unknown private fears, ambitions, humor, rivals, or preferences remain unknown until supported.
