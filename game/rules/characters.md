# Character Model and Materialization

`game/data/mechanics/economy.json` owns procurement and maintenance arithmetic used by character/equipment settlement.


Exact characters use physical and social state plus a narrative profile: core traits, values, speech pattern, behavioral tell, conflict style, current objective, concealed concern, knowledge boundary, and relationship posture. Materialization must reconcile source unit, age, health, role, equipment, location, and prior settled history without canon bonuses.




skill_order: Sword, Polearms, Heavy Weapons, Bow, Crossbow, Shield, Athletics, Grappling, Unarmed, Riding, Formation Fighting, Survival, Stealth, Scouting, Medicine, Engineering, Leadership, Formation Command, Tactics, Strategy, Logistics

## Universal character kernel

Every persistent person uses the same underlying model: identity, source population, generation seed and schema, age, sex, body, health, nine attributes, nonzero or relevant skills, specializations, aptitude, potential, certification, combat experience, readiness, injuries, loadout, service history, and development evidence.

Attribute order for compact personnel arrays:

`Strength, Agility, Endurance, Toughness, Coordination, Awareness, Composure, Intelligence, Presence`.

Compact exact-character skill-array order:

`Sword, Polearms, Heavy Weapons, Bow, Crossbow, Shield, Athletics, Grappling, Unarmed, Riding, Formation Fighting, Survival, Stealth, Scouting, Medicine, Engineering, Leadership, Formation Command, Tactics, Strategy, Logistics`. Professional disciplines are sparse named values: `Intelligence Operations, Diplomacy, Law, Trade, Governance`.

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
- Dynasty Warriors-scale hero: above 150 in decisive domains, supported by Formation Fighting, body, endurance, equipment, geometry, and present condition.

Scores remain uncapped. No number creates magic, immunity, teleportation, or simultaneous presence in several sectors.

## Age, adulthood, and service eligibility

Age 16 is ordinary adult eligibility and the minimum ordinary state conscription age. Voluntary House Tang battlefield service may begin at age 10 under direct family authorization, a full-sheet adult protector, exact age-appropriate equipment, health, and capability checks. Ages 10-15 receive no adult civil authority, independent command, contractual capacity, or physical capability by age alone.

Character height, wingspan, arm span, body radius, personal reach, and body-growth measurements are not game fields. Combat reach comes only from the current weapon or fixed combat-method pattern.

## Equipment condition, fit, and concrete craft
Equipment capability comes from actual pattern fields, current condition, fit, carriage, and any explicitly named physical craft trait.

A craft trait is not a prestige label. It must alter exactly recorded fields, such as reduced mass, improved balance/handling, increased structural capacity, better fit, lower maintenance, or altered material resistance. The changed catalog or exact-item values enter ordinary formulas once. Decorative workmanship, famous ownership, or price does not create combat power.

Condition and fit use `game/rules/battle.md#condition-fit-and-craft`. Exact consequential items may store continuous condition. Aggregate stocks use condition-band quantities.
## Catalog economic fields
Every physical pattern has a numeric `baseline_value_silver` for one sound reference item. Actual purchase, sale, manufacture, repair, and replacement use stock, market depth, scarcity, legality, bulk, materials, labor, craft capability, route, condition, and time.

Procurement value is calculated by `game/data/mechanics/economy.json`.

Concrete custom work costs the actual materials, skilled labor, tools, supervision, inspection, failure risk, and time needed to change a named field. Money alone cannot create a physical improvement that the workshop cannot produce.

Routine maintenance reserve is calculated by `game/data/mechanics/economy.json`.

Operating-mode maintenance factors are defined only in `game/data/mechanics/economy.json`. Maintenance is realized only when labor, tools, materials, access, and time are committed.
## Canonical position modifiers

`game/rules/combat.md` and `game/rules/battle.md` own combat resolution. Catalog circumstances map only to the fixed positional levels in `game/data/mechanics/combat.json`; physically impossible reach, clearance, footing, perception, or method makes the action illegal rather than creating an unbounded modifier.

Examples: a small reach edge is minor; a stable flank is major; a genuinely undetected rear attack is decisive until detection; a prepared spear line is clear or major according to completed formation state; awkward but legal clearance is minor/clear; impossible minimum range is illegal. Fatigue and injuries normally act through usable values, not a second duplicate flat penalty.

## Stable and current ownership
Stable identity, body, attributes, skills, aptitude, potential, and service history live in the character owner. Current action, target, location within the hot scene, immediate knowledge use, and next decision live in `state/scene.json` and the referenced typed owner. Omitted skills equal zero.

## Development parity

All permanent development uses `game/rules/growth.md`. Name, player status, canon status, resolution tier, active loading, and narrative attention are not inputs.

## qualification-profile-routing

`qualification_personal_uncredentialed` owns no institutional authority; `qualification_scout_qualified`, `qualification_healer_advanced`, `qualification_guard_qualified`, `qualification_officer_qualified`, `qualification_elite_martial_advanced`, `qualification_civil_advanced`, and `qualification_commercial_qualified` record role legality only. They do not change attributes or skills. Exact sparse certifications may override a profile after a saved assessment.
## general-opposed-capability-routing
Opposed non-combat capability uses the same scale for player and NPC: relevant skill and specialization plus weighted attributes, legal equipment or records, position, information quality, health, fatigue, environmental conditions, and committed uncertainty. Development status, naming, canon status, and loaded state provide no bonus. Domain procedures in `game/rules/personal-force.md` determine evidence, detection, delay, and consequences.

## birth-date-and-age
Every already-born persistent person stores one exact `birth_date`. `age` is a validated checkpoint cache, not a second mutable truth. Future identities store no birth date before a causal birth. Life stage, adulthood, age-based law, maturation, and aging pressure derive from birth date plus world time through `game/rules/growth.md#birthday-and-age-authority`.

## compact-routed-maturation

The human kernel supports compact settlement for aggregate populations and institution-backed anonymous labor pools. Age changes only at crossed birthdays. Childhood and adolescence process health, nutrition, coordination, endurance, language, education capacity, and age-appropriate labor or practice without generating an adult capability sheet.

Poor nutrition, illness, injury, displacement, excessive labor, unsafe training, missing guardians, and lack of instruction reduce or block development. Household wealth, rank, or canon status never grants fixed capability. Life-stage ceilings prevent infants and children from receiving adult training, command, office, or combat competence.

## authoritative-and-derived-character-fields

Birth date, current health, equipment custody, location, service, and appointments are authoritative facts. Age, life stage, current load ratio, authority display, remaining recovery time, and narrative status are derived. Rebuild them at startup, after affected transactions, and checkpoint.

A birthday creates no automatic attribute, skill, knowledge, rank, office, or authority. Age affects development and health only through the owned aging rules and actual evidence.

## Executable talent representation

A character owner may store universal domain aptitude and potential factors, but not prose-only dormant talents or promised future abilities. Current attributes, skills, specializations, qualifications, and experience must come from actual persisted evidence or later development receipts. Omitted skills remain zero.

## Compressed recurring exact profiles

Before the ordinary omitted-skill-equals-zero rule is applied, a compressed exact profile expands its stored template, immutable seed, accumulated unit receipts, age stage, health state, and explicit overrides. The expanded array is exact. A static source-identity catalog entry has no capability profile to expand.



## Persistent-name rule

Anonymous aggregate people have no personal identity record. When a generated ordinary person is lawfully materialized as a persistent individual-lite person, assign one stable personal name and ID immediately and preserve them through any later exact-character promotion. A source-canon name is preserved once it is lawfully bound to a current person. Never delay a persistent individual's name until full-sheet promotion.

## Individual-lite combat sheet

An individual-lite owner is a persistent named person used when unit resolution is insufficient but a full narrative character is not justified. It keeps one stable ID, canonical display name, birth date, body, appearance, exact capability, aptitude, health, fatigue, equipment state or role-profile reference, location, assignment, combat/service history, compact personality when supported, important relationship references when supported, and current duty/goal when supported. It does not require a large biography or fabricated social depth. Promotion to a full exact character preserves the same identity and all existing mechanical/history state.

Anonymous ordinary people remain aggregate population/manpower state; armed organized personnel belong to units. Generated anonymous people receive a personal name only when lawful materialization creates a persistent individual; a source-canon name may be bound only after current existence is proven.

## Named owner and unit-aggregate separation

A named full-sheet character is one separate body owner. If that person was materialized from an aggregate unit, the unit headcount is deducted exactly once at materialization and the named person is thereafter tracked separately. Removing or killing the named person must never deduct the unit a second time. Deterministic aggregate casualty resolution excludes already-materialized named people.




## Runtime tiers

- Full exact character: complete independently simulated narrative/mechanical actor with exact body, capability, knowledge, relationships, goals and activity when causally required.
- Individual-lite person: persistent named individual with exact body/capability/equipment/service state and compact narrative state.
- Aggregate person: ordinary population/manpower member represented only through a population, institution or unit owner.
- Source identity catalog entry: static canonical name/source hint only; it is not a current person representation.

## Separation of source names and runtime state

A source identity catalog never asserts current location, health, inventory, office, travel, knowledge, capability or existence. Exact/lite runtime facts require a current person owner. Anonymous institutional staffing remains aggregate and cannot participate in exact personal agency, combat, relationships, private inventory, or individual opposed checks until one conserved person is lawfully materialized.

## Identity activation

A source-canon identity cannot act merely because its name exists in the catalog. Activation first proves current existence and resolves a lawful source population/unit/role, age or life stage when causal, location, health, authority, equipment, knowledge and current purpose. Materialization then creates one exact/lite owner and conserves the same real body exactly once. Missing inputs fail closed.

## Context routing

Startup loads no source identity catalog or external profile collection. Known materialized IDs use direct owners. A source-name lookup loads only `game/data/people/latent-identities.json`, then the one causal source owner if activation is required. Large scenes use deterministic sector, formation, authority or owner batches sized to available context. Batch size may change; semantic coverage may not.

## Anti-bloat invariants

- no complete name lists for anonymous populations or units;
- no campaign-original exact quota filler;
- no generic random state, age, role, office, location, health, equipment, knowledge, goal or elite skill;
- static source identities have no personal periodic clocks or mutable profile seeds;
- aggregate institutional staffing carries no secret name, personality, biography, private inventory, relationship graph or exact personal skill sheet;
- no profile definition is treated as a living runtime body without current-existence evidence.

## Ordinary-person naming
Units do not carry complete name lists. Exact names are materialized only through the mandatory triggers in `game/rules/agency.md`. Compact casualty and memorial records do not become active character sheets.


## canonical-name narration

Every materialized named person retains one canonical display name. A source-canon catalog name is used only after the identity is lawfully bound to a current person.


## Initial-date projection safety

A source-canon catalog entry is not an automatic 245 BCE body state. On activation, reconstruct only state supported by the current source owner and explicit initial evidence. Future achievements, future ranks and later-series peak values cannot be imported as initial facts.




## Scope

This module creates a recurring exact canonical actor or a full-sheet person from a real unit, population, role incumbent, or source identity whose current existence has been proven. It never invents state affiliation, initial existence, age, role, location, office, equipment, knowledge, relationship, health, or authority from a random seed.

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

## Character materialization from conserved cohorts

When an anonymous soldier becomes persistently named, runtime materialization consumes or reclassifies exactly one body from the person's actual source cohort. Capability is sampled deterministically from that cohort's current attribute means/spreads, skill means/spreads, professional skills, aptitude, recruitment background, and already-settled development. A command billet may select above the source-cohort mean only through the bounded command-selection logic that still derives from that cohort.

There is no generic role-template stat package and no random seed that may invent affiliation, history, equipment, authority, location, relationships, wounds, or knowledge. Existing exact evidence and conserved source state remain authoritative.

### Application order

1. Resolve the exact source force/cohort and, when applicable, formation allocation.
2. Consume or reclassify one conserved body.
3. Deterministically project capability from the current source cohort.
4. Preserve the source cohort reference and exact equipment-custody mode.
5. Apply only later lawful development, injury, equipment, appointment, and relationship changes through their owning systems.

## Cohort member materialization

Named individual-lite members retain their saved canonical identities. Anonymous cohort members have no hidden complete name roster. When one becomes causally important enough to materialize, reclassify exactly one surviving body from the authoritative source cohort/formation allocation, assign one stable canonical identity through the registered deterministic procedure, inherit only the current cohort capability/provenance facts required by mechanics, and create no replacement body. Full session or unit-history diaries are not materialization authority.


## body and appearance
Every exact or character-lite person has a birth date, derived age, adult height, growth profile to age 18, dynamic weight, frame, and appearance. Height and weight participate in personal combat physics. Mass units use distributions instead of individual body records. Named characters remain individuals even when commanding unit-based House or state troops.

Named military officers remain individual people even when operating with mass forces. Their command-unit attachment is separate from unit representation.


## Information-density rule

Exact characters do not require duplicated `character_profile` and `personality_signature` blobs, a minimum relationship count, or fabricated individuality. `behavior`, when present, is the compact character-specific narrative profile. Existing bespoke behavior outranks generic generated filler. Unknown private fears, ambitions, humor, rivals, or preferences remain unknown until supported.
