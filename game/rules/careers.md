# Recruitment, Service, Careers, and Command

`game/data/mechanics/career.json` is the structured numerical authority for command-capacity formulas, command-grade thresholds, merit arithmetic, service-model terms, deterministic character materialization, and role-template starting profiles. `game/data/mechanics/economy.json` owns recruitment and payroll costs. `game/data/mechanics/training.json` owns development and qualification evidence.

## Separate concepts

Institutional membership, rank, command grade, appointment, assigned strength, qualification, experience, merit, authority, and service contract are separate state. A high-ranked person may hold no field command. An acting commander may temporarily lead above formal rank. A great fighter may be unqualified for large-unit command.

Promotion or appointment never grants permanent capability.

## Recruitment

Recruitment requires a real source population, lawful or coercive authority, candidates, recruiters, time, route access, screening, entry cost, equipment, training capacity, and a destination owner. Rejected, missing, or deserting candidates still consume resources already spent.

No recruitment action creates people from a percentage or target number. Accepted recruits transfer from an exact population owner.

## Service models

All supported service models and their terms are defined in `game/data/mechanics/career.json`. A formation's current service contract controls obligations such as pay basis, bounty, advance, family support, service term, mobilization, and exit. A troop class may suggest a default, but the actual formation contract is authoritative.

Changing service model is a timed institutional action. It does not create loyalty, equipment, land, money, readiness, or training by relabeling the force.

## Command grades and capacity

Command grades provide a universal mechanical scale beneath faction-specific titles. Eligibility for an appointment requires the appropriate command-capacity threshold plus qualification, authority, vacancy or lawful acting authority, and any institution-specific conditions.

Command capacity does not add a magical combat-stat bonus to subordinates. It determines how much complexity and force a commander can coherently control under current staff, communications, doctrine familiarity, cohesion, health, fatigue, terrain, and political authority.

## Appointments

An appointment records the office/formation, holder, authority scope, start, lawful end conditions, acting/permanent status, command limits, and superior authority. Personnel assignments remain separate from rank.

A person cannot simultaneously hold incompatible active service records unless an explicit lawful dual-office or allied arrangement permits it.

## Merit

Merit requires an actual objective, difficulty, responsibility, result, evidence, institutional relevance, and saved adjustment factors. Missing evidence blocks formal merit assessment rather than inviting a narrative guess.

Merit can influence promotion and appointment but does not guarantee either. Vacancy, trust, politics, qualification, authority, institutional practice, and current need remain causal factors.

## Promotion and demotion

Promotion requires evidence, qualification, lawful authority, and a valid institutional route. Demotion, removal, suspension, or reassignment likewise requires authority and a saved cause.

Prior service in another force is evidence, not automatic rank entitlement. A receiving institution may recognize, reduce, raise, honor, probationarily recognize, or reject prior rank according to its lawful process.

## Character materialization

When a recurring or unit-bound person becomes exact, materialization uses the registered role template and deterministic seed variation in `game/data/mechanics/career.json`, then reconciles source-unit development, age, health, occupation, service history, equipment, location, relationships, and explicit evidence.

The source population loses exactly one person. The seed may vary capability within the registered bounds but may not choose identity, affiliation, history, equipment, authority, or world facts.

## Personal and issued forces

Tang Wei's personal troops are cohort-first at scale, with person-lite or exact records materialized only for individually relevant existing members. State, allied, mercenary, and institutional forces likewise remain aggregate at rank-and-file scale and remain owned by their source institution when assigned under Tang Wei's command unless a real transfer changes ownership.

## Invariants

- no recruitment without a conserved source person;
- service model is a contract, not a stat bonus;
- rank, command, qualification, merit, and appointment remain separate;
- promotion grants no permanent stats;
- command capacity controls lawful/coherent span, not subordinate power;
- materialization deducts one source person and creates no duplicate;
- named or player status provides no career bonus.
