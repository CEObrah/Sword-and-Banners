# World Simulation

Sword & Banners is a living political and military simulation. Tang Wei is important to his own story, but he is not the scheduler for the rest of the world.

## Independent actors

States, Houses, factions, institutions, commanders, mercenary companies, households, markets, and materialized people may act without Wei initiating them when the runtime's causal hosts and authority rules permit it.

Their decisions should arise from saved state such as:
- goals and priorities;
- authority and office;
- relationships and reputation access;
- military doctrine and command custody;
- personnel and formations;
- treasury and economic capacity;
- population and recruitment;
- territory and fortifications;
- intelligence and misinformation;
- logistics and travel time;
- family and succession concerns;
- current threats and obligations;
- bounded operational history and learned performance evidence.

Do not bend organizational behavior to make the player's next scene convenient.

## Operational memory and learned choice

Autonomous organizations may retain bounded operational memory when the runtime provides it. Treat that memory as evidence, not a second authority. Exact formations, commanders, operations, battle records, treasuries, relationships, reputation profiles, locations, and casualties remain authoritative in their normal owners.

When an organization has several lawful assets available, prefer runtime-grounded assignment that considers objective fit, readiness, fatigue, logistics, commander capability, prior performance, current commitments, and complementary roles rather than arbitrary list order.

A formation that repeatedly succeeds, fails, suffers replacement, accumulates training, or develops relevant experience may influence later assignments only through saved runtime evidence. Never invent institutional learning merely because it would make the story more dramatic.

## Concurrent autonomous work

A living state or House may have several simultaneous concerns. When the runtime exposes bounded operational capacity, allow multiple concurrent operations rather than forcing every institution through a single global activity slot.

Concurrency is constrained by exact resources. The same formation, commander, treasury, institution slot, courier, or material reserve cannot satisfy several commitments at once unless the runtime explicitly permits it. Capacity limits are simulation rules, not narrative suggestions.

## Offscreen time matters

Advancing time can progress independent causal hosts. During Wei's travel or training, other actors may recruit, move, report, train, appoint, negotiate, build, spend, fight, or respond within runtime rules.

Offscreen progression is keyed to the authoritative campaign-time delta, not to conversational turns. Production records a global `causal_settled_through` frontier and periodically reconciles the bounded scheduler registry while a long skip is still running. A one-hour or one-day advance with no dirty routing need not rescan every owner; a multi-month skip still crosses weekly reconciliation checkpoints and every due domain host in chronological order. If a hard player wake interrupts the skip, both world time and the causal frontier stop at that exact reached instant.

Do not narrate offscreen truth automatically. Wei learns about offscreen developments only through lawful perception or information delivery.

## Living-world delivery and local scene life

An autonomous world is not useful merely because offscreen state changes correctly; lawful developments must eventually reach Tang Wei through their real report, courier, rumor, witness, court, House, market, military or travel channels when they become player-relevant. Do not manufacture a new crisis just to prevent silence, and do not leave a meaningful completed development permanently trapped in backend state.

The opposite boundary matters too: **ordinary local human life does not require an offscreen world event**. When exact present people and current pressures already support a scene, the LLM may direct reversible conversation, interruption, work, humor, discomfort, disagreement and NPC-to-NPC interaction from those established facts. Python should simulate hard world change and deliver causal evidence; it should not pre-script the room merely to make it feel alive.

## Representation scale

The runtime may represent some actors as fully materialized people or formations and others as colder causal hosts until they become relevant.

Do not confuse representation depth with importance. A cold host can still create consequential world events. Materialization should occur through runtime systems rather than the GM inventing a full person record in prose.

Avoid global polling in narration or reasoning. Fresh play context and bounded reads should expose what matters to the current turn.

## States and Houses

A state is not one NPC. It contains rulers, offices, military commands, institutions, noble Houses, populations, treasuries, routes, fortifications, interests, and internal friction.

A House is not automatically subordinate to Wei even when it is House Tang. Saved authority determines what Wei may command, spend, promise, or delegate.

Differentiate:
- ownership;
- administrative control;
- military command;
- state office;
- patronage;
- family status.

These can overlap but are not interchangeable.

## Armies, formations, and lifecycle

Military organizations can recruit, replace losses, train, mobilize, change commander, receive assignment, move, resupply, fortify, raid, besiege, defend, and fight when current runtime capabilities allow it.

Do not assume a formation remains static merely because Wei is elsewhere.

Command custody is exact. A formation belonging to a state or House does not automatically obey every member of that organization.

Where the runtime records lifecycle or operational-memory data, distinguish standing formations from temporary operational groupings. Replacement policy, target strength, current personnel, training history, prior deployments, casualties, and current assignments should matter to future decisions. A persistent formation should not be silently dissolved merely because one operation ends.

NPC military development should obey the same material principles as player-controlled development. Training requires elapsed time and lawful opportunity. Doctrine should arise from saved composition, command, training, equipment, history, and explicit doctrine authority rather than free competence granted because an NPC is offscreen.

## Scale-specific personnel representation

Use aggregate conserved cohorts for ordinary state armies, Inner Walls ranks, House Tang troops, and ordinary Tang Champions. Assignment to Wei does not make every assigned soldier a persistent individual. Keep important named officers exact and materialize an ordinary cohort member only when individual relevance requires it, conserving that same body.

Tang Wei's personal force is also cohort-first so it can scale to thousands. A player-visible recruitment campaign may resolve candidate screening and training at higher detail, but accepted ordinary retainers remain conserved cohort members. Materialize a stable `person-lite` or exact person only when one member becomes named, exceptional, socially important, specialized, command-relevant, or otherwise individually relevant. The player camera makes this more frequent around Wei, but the same materialization rule can apply to any force. A formation summary may cache group capability, but it must never replace or duplicate a materialized person.

Recruitment capability is runtime-owned. Population strata conserve bodies; registered occupational/background profiles determine starting distributions; registered selection conditions those distributions; training/service/combat then develops them. Never let narration or ChatGPT choose ad hoc recruit statistics.

## Exact people and aggregate development

Named exact people and aggregate cohorts must not receive the same elapsed development twice. If House, institutional, formation, cohort, or personal activity systems overlap, one authoritative progression cursor or settlement path must own each eligible period.

When exact House members receive development from House institutions, preserve their individual state and do not also award an independent aggregate copy of the same training. If ownership is ambiguous, fail closed and flag the overlap OOC rather than compounding progression.

## Exact identity and aggregate conservation

An exact materialized person may also represent one slot inside a larger conserved personnel or population pool. Those are two views of one person, not two people.

When materialization, recruitment, graduation, promotion, transfer, demobilization, casualty settlement, or another pipeline changes that shared representation, synchronize the exact identity and aggregate counts inside the same causal settlement. Reclassify or consume an existing anonymous slot rather than creating extra headcount. If an exact person leaves one cohort for another, the aggregate representation must move with the same conserved identity rather than leaving a duplicate anonymous copy behind.

Do not infer that every aggregate transfer must materialize named people. Exact/aggregate synchronization applies only when a materialized identity is already represented inside the affected conserved flow or when the runtime explicitly materializes one from it.

## Economy and logistics

Wealth is not infinite. Armies consume supply. Horses require forage. Institutions use capacity. Projects take labor and material. Markets respond through the runtime's economic systems.

Logistics should create causal pressure without becoming arbitrary punishment. Use actual runtime state and rules.

## Information propagation

World truth moves through scouts, couriers, officials, merchants, captives, witnesses, letters, institutional records, rumor, and other supported channels.

Distance creates delay. Political access affects who receives what. Reputation knowledge can be local to the communities that plausibly know it.

Do not grant instant global awareness after a battle or appointment unless the runtime establishes that propagation.

## Social consequences from world events

A meaningful world event may become evidence for reputation or relationships without a player manually issuing a social command. Shared service, public success, failure, rescue, betrayal, command performance, appointments, contracts, marriage, political conflict, witnessed violence, and reported battlefield conduct may propagate socially when the runtime establishes the witnesses, reports, audience, or relationship pathway.

Do not manufacture universal fame. Social effects require an audience or evidence route, and different audiences may learn different things at different times.

## High-salience wake boundaries

Compressed autonomous resolution must not silently carry Wei through an irreversible consequential decision that belongs to the player.

If the runtime reports an actual pending high-salience wake, stop the broad time skip or autonomous continuation and hand the situation back to the player. Examples include imminent hostile contact while Wei is the exact commander or another runtime-defined irreversible state whose settlement cannot lawfully continue without his immediate response.

Do not treat a wake as a failed simulation. It is a causal boundary: the world has progressed far enough that this specific causal process cannot continue safely without player input. Ordinary voluntary offers and commissions may still become actionable decisions, but they persist in their exact owners and need not freeze unrelated chronology or commands.

## Historical pressure without predetermined history

The campaign is grounded in the Warring States period, but future history is not a script.

Use game data for established background, known people, institutions, past events, geopolitical conditions, and conditional historical pressures. Do not force a famous future battle, death, conquest, appointment, or alliance merely because it occurred historically outside the simulation.

If player or autonomous actions change the conditions that produced a historical event, let the runtime's causality govern the result.

## Player relevance

The world should bring Wei consequences appropriate to his location, relationships, reputation, office, command, House position, and prior actions. It should not bring him every important event.

A believable world includes consequential events that occur without Wei and sometimes never concern him directly.

## Time and distance

Time is physical. Couriers travel. Armies march. Bureaucracies process documents. Sieges take labor. Recovery takes time. Recruits require integration. Roads and crossings constrain movement.

Never compress these away merely because a strategic choice is phrased broadly. Let runtime time advancement and hard causal boundaries decide what completes before interruption.

## Consequences must propagate across systems

Do not let an autonomous battle, appointment, mission-like operation, contract, death, marriage, public dispute, or major report remain isolated inside the subsystem that resolved it when the runtime has causal pathways for wider consequences. Witnessed or reported events may affect reputation, relationships, information, logistics, command availability, House memory, institutional priorities, succession, or later autonomous decisions only when the required evidence and authority exist.

Compact operational history or memory may summarize evidence for later autonomous choices, but it must never replace the authoritative battle, person, relationship, reputation, treasury, formation, information, or family state it references.

## Player-neutral autonomy

Protect the player from autonomous control because the player is marked as player-controlled campaign authority, not because one hard-coded character name receives special immunity. Apply the same autonomous eligibility, resource, knowledge, and timing laws to comparable NPCs and organizations unless saved authority or state creates a real difference.

## Deferred settlement

A causal host's `resolved_through` cursor is evidence that eligible work through that point has actually been settled, not a mirror of global campaign time. A `safe_through` horizon may permit bounded lazy settlement, but it must never erase training, recovery, economic, social, institutional, family, or other elapsed work that was actually eligible. Before a capability-dependent resolution, the relevant deferred progression must be settled or proven to have produced zero eligible activity.

## Progression bounds

Soft ceilings and diminishing returns are not numerical bounds. When the runtime exposes an absolute progression limit, treat it as a hard invariant for player and NPC development alike. Long time skips, high aptitude, aggregate settlement, residual banks, or repeated autonomous reviews must never push an exact stat beyond the registered scale.

## Retinues, commissions, obligations, and care

Use persistent command groups as the bridge between exact people and formations. A retinue can accumulate familiarity, roles, standing orders and communication structure while retaining zero independent manpower. Do not flatten named officers, specialists, household companions or attached formations into one aggregate when their exact identity can change an outcome.

Commissions are delayed institutional assignments. A request does not create an offer. The runtime commits the assignment objective/location before player tactics and settles the response through causal time. An arrived offer persists in its exact commission owner and surfaces as a player decision without becoming a scheduler wake by itself. Any hidden risk profile is an issuer-side assessment only, never authority that actual opposition exists. Acceptance is separate from completion, and a player report can support later settlement only through relevant runtime-established evidence.

Commitments represent durable promises/obligations with obligor, beneficiary, due boundary, status and evidence. They do not transfer the underlying money, formation, office or asset by themselves; the owning subsystem must still perform the promised act. An obligor may submit an evidence-backed fulfillment claim, but a voluntary social obligation is not objectively fulfilled until the beneficiary confirms it or another authoritative domain mechanic establishes fulfillment.

Medical treatment is persistent chronology. Stabilization, treatment, surgery and rehabilitation require exact people, location, practitioner capability and real elapsed time. A high-salience world interruption stops the work rather than allowing the command to receive unearned completion credit.

## Epistemic intelligence and fog of war

Treat military and political intelligence as knowledge with provenance rather than as an omniscient strategic overlay. Scouts, merchants, prisoners, couriers, documents, officials and witnesses can carry claims with different confidence and channels. Corroboration can strengthen player reasoning, but the runtime must not silently convert a report into world truth.

Use investigations when the question is causal and evidence-driven. Use ordinary information delivery when the fact is already lawfully known and merely needs to travel. This distinction keeps espionage, reconnaissance, court inquiry and counterintelligence playable without letting narration invent hidden answers.
