# Development and Aging

`game/data/mechanics/training.json` is numerical authority for ordinary permanent development, training factors, EDU, score costs, aptitude/potential interaction, instructor capacity, age-learning factors, ordinary age-performance references, rust, aging pressure, experience modifiers, and representation neutrality. `game/data/development/model.json` defines the shared progression topology and exceptional-development contract. `runtime/sword_runtime/development.py` must implement both without introducing a conflicting hard cap.

## Development parity

Tang Wei, exact NPCs, character-lite people, and personnel represented through unit aggregates use the same underlying development law. Representation changes storage and calculation granularity only. It never changes learning efficiency, promotion probability, experience gain, resource efficiency, or access to elite qualification.

Naming, historical importance, player status, screen time, and loaded state provide no development bonus.

## Capability scale

Trainable aptitude and capability values are nonnegative and have no universal upper numerical bound. `200` is a legendary reference value, not a hard maximum. Existing values above 200 are valid if their provenance is valid, and future values may cross 200 through the exceptional-progression law.

Routine practice, instruction, study, conditioning, sparring, drills, ordinary field exercises, and autonomous calendar training may raise a skill only through the routine-training ceiling registered in the development model. They may continue to create bounded target-specific consolidation at the ceiling, but elapsed time alone cannot create legendary advancement.

This is a progression-topology rule, not merely a larger point cost. Long-running schedulers, dormant people, House cohorts, formations, and institutions must never manufacture extraordinary exact people merely because enough years passed.

## Exceptional progression

Above the routine-training ceiling, permanent whole-point growth is exact-person only. One resolution advances one selected target by one point and must consume already-persisted causal evidence that names that person.

The evidence must be relevant to the capability, unused by that person, deep enough for the current band, and drawn from enough distinct contexts. The person must also have accumulated target-specific consolidation through lawful practice and must satisfy the saved cooldown from any prior breakthrough on that target.

Mission prestige, office, fame, kills, elapsed calendar time, narration, or caller assertions never award an exceptional point by themselves. Higher reference bands require progressively more evidence, contextual novelty, consolidation, and recovery time. There is no final numerical wall.

Martial capability requires relevant dangerous physical evidence. Command capability requires real decision burden and consequences. Civil, technical, diplomatic, medical, engineering, intelligence, trade, and administrative capabilities require consequential evidence in their own domains. Classroom work may consolidate knowledge but cannot fabricate field judgment.

An aggregate or cohort cannot consume exact-person breakthrough evidence. If an exceptional individual becomes causally important, split or materialize that person conservatively before extraordinary advancement.

## Evidence and time

Permanent growth requires a saved activity or lawful stable routine with real elapsed time. A development block records the subject, duration, training/work mode, competency shares, instructor access, student count, facility, equipment, health, fatigue/recovery, feedback, interruptions, and evidence source.

The same evidence settles once. Missing time, instructor capacity, equipment, facility, health, recovery, or opportunity reduces or blocks progress instead of being filled by narration.

## Aptitude and potential

Aptitude affects learning rate. Potential and soft ceilings affect diminishing returns. Neither grants free points and neither is a universal cap. High aptitude means a person converts comparable valid work into development more efficiently under the registered formula.

## Instructor, facility, and equipment conservation

Instructor hours, facility slots, equipment sets, horses, ammunition, tools, food, and other training inputs are conserved across simultaneous activity. Parallel cohorts share real capacity. One instructor or drill ground cannot be counted at full capacity by several concurrent programs.

Large-group instruction may scale where the registered activity permits it, but advanced correction, specialist equipment, mounts, and constrained facilities remain capacity-limited. Missions, deployments, injuries, travel, institutional duty, insufficient recovery, and material shortages preempt or reduce routine training when they occupy the same time or resources.

## Standing training and player agency

Autonomous development never silently schedules the player character merely because a team, House, or institution has a routine. Player participation requires a persisted standing instruction that names the activity or group, its bounded target cycle, and the circumstances under which it may run. Such a standing instruction remains revocable and must never double-count Wei across overlapping schedules.

NPCs may follow lawful saved standing orders within their authority, location, availability, workload, recovery, and resource constraints. A general preference is not an invented instructor appointment, travel order, or training commitment.

## Experience

Technical training and field experience are separate. Combat and command experience changes only through saved operational exposure. Kills alone do not grant experience. Exposure records role, pressure, duration, decision burden, casualties, and outcome.

Training cannot fabricate battlefield judgment, command experience, campaign history, governance crises, diplomatic outcomes, engineering consequences, or other exceptional evidence.

## Qualification and promotion

Training changes capability. Qualification certifies capability for a specific institution or role. Promotion changes institutional rank or appointment. These are separate.

A unit never upgrades wholesale because enough time passed. Qualified subsets transfer between ranks or quality tiers while headcount conserves. Elite and politically important personnel progressively split to smaller units or exact representation.

Promotion grants no permanent attributes or skills.

## Exact and character-lite people

Exact and lite people retain individual development state. Shared instruction may be batch-calculated when conditions are identical, but each person's starting capability, aptitude, health, fatigue, attendance, injuries, and prior mastery remain their own inputs.

## Units

Units store capability and aptitude distributions plus development banks. Training changes distributions, not one magical average rank. When a tail becomes rare, elite, specialized, promoted, politically important, or directly interactive, that subset splits or materializes conservatively.

Materialization deducts a real source slot and imports the conserved source person/unit history exactly once.

## Children and aging

Age derives from exact birth date. Body growth is physical state, not free skill. Ordinary age-performance references and age-learning factors are defined in `game/data/mechanics/training.json`.

Raising an age reference grants no learned capability. Skill, command, education, craft, and professional development require actual opportunity and evidence. Exceptional prodigies may exceed ordinary age references only through real development.

Aging reviews can change maturation, recovery, health pressure, and current performance. Injuries, disease, deprivation, nutrition, exceptional health, and physical maintenance can alter the normal curve when saved.

## Rust and maintenance

Unused skills may lose accessible performance according to the structured rust rules. Maintenance activity can prevent or reduce rust when real time and opportunity support it. Rust does not erase historical knowledge automatically.

## Long skips

Long time skips settle development chronologically. Stable identical intervals may batch only while inputs remain unchanged. Injury, promotion, instructor change, war, travel, equipment loss, shortage, assignment change, illness, mission duty, or another material event splits the batch.

A five-year skip is five years of real opportunity and constraints, not a flat bonus. Reaching the routine ceiling during a long skip does not authorize the rest of the interval to mint exceptional points.

## Invariants

- trainable aptitude and capability have no universal hard maximum;
- 200 is a reference value, not a cap;
- routine training cannot cross the exceptional threshold by itself;
- exceptional points are exact-person, evidence-backed, target-specific, one-use, and cooldown-bound;
- representation efficiency is identical across exact, lite, unit, and large-unit;
- no progress without supported time and opportunity;
- instructor, facility, equipment, and overlapping schedule capacity conserve;
- technical training does not fabricate operational experience;
- promotion transfers qualified people rather than transforming whole units;
- age changes physiology and ordinary performance expectations, not free learned skill;
- materialization creates no duplicate body or history.
