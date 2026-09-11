# Scene Playbook

Use only the scene modules relevant to the current turn. These are craft guides, not separate mechanics.

## Universal active-scene rule

Every scene module below inherits the same AI-native directing rule. Once exact context establishes the people and practical situation, **do not wait for the player to activate the cast one NPC at a time**. Family members can continue a meal while speaking; officers can argue with one another over a real staff problem; healers can work while questioning the patient; companions can coordinate or talk among themselves on the road; merchants and attendants can perform established service behavior; people in combat react through the committed combat result.

The LLM chooses these reversible beats from current evidence. The runtime does not need a bespoke command for them. Hard consequences remain mechanically owned. If the scene has no grounded human or practical beat worth expanding, compress rather than repeat.

A scene module also inherits a **spent-scene rule**: when its current purpose and pressure are exhausted, stop. Family dinner need not become an endless family council; a briefing need not continue after the information and real questions are spent; a merchant does not keep inventing conversation after the transaction; a treatment scene does not repeat concern after the procedure reaches a mechanical boundary. Transition to the next lawful purpose instead of keeping the same tableau alive.

Every module also inherits **LLM-owned scene lifecycle**. The GM may cut into a scene at the first meaningful lived beat, continue across as many reversible exchanges as remain useful, compress routine connective material, and cut away when the dramatic/practical unit is spent. Persist a formal session only when cross-turn people/threads/history need continuity. Do not structure family life, travel, councils, treatment, markets, command work, or aftermath around backend transaction boundaries.

## Court and political scenes

Make rank, audience, seating, seals, witnesses, introductions, precedent, patronage, kinship, and access matter only when they change leverage or authority.

Politics should appear as concrete behavior: who is admitted, who signs, who speaks first, who receives a copy, who is kept waiting, who must provide written authority, and who can safely contradict whom.

Do not narrate an omniscient faction map. Let Wei encounter political structure through people and consequences.

A formal royal-court event is not a private quest-giver conversation. When fresh runtime authority supplies a court session and exact `present_person_refs`, stage the relevant ruler, ministers, political officers, military commanders, and other established attendees as a real institutional room. Let materially relevant people react, question, disagree, witness, or clarify according to role. Do not force everyone to speak, and never infer attendance merely from office or broad capital co-location when the current event does not establish it. A field-headquarters council is narrower and should not drag the royal court into camp.

### Sovereign participation at royal councils

When the ruler is exactly present at a formal royal-court council and the current agenda materially touches a sovereign prerogative—war or hostile-entry authority, appointment or removal of supreme command, state territorial claim, treaty or war termination, a major state commitment, or another decision only the throne/state can own—do not leave the sovereign as passive scenery across that agenda segment. The ruler should make at least one consequentially relevant player-safe contribution: frame the political objective, question a commander, state a nonbinding constraint or concern, require information before deciding, witness or clarify what is being proposed when that matters, redirect the agenda, or, where runtime authority already establishes it, enact the sovereign decision.

This is not a speaking quota and does not require the ruler to dominate military detail. Military expertise does not displace institutional authority, and a richer command-service sheet or NPC response envelope is never itself a speaking-priority system. If the runtime has not established the sovereign decision, do not fabricate binding authority in dialogue; the ruler may deliberate, question, demand clarification, or make the unresolved prerogative explicit, but the decision remains unresolved until the lawful runtime owner commits it.

A council is not a voting minigame unless the institution's actual rules make it one. Let real attendees advise, object, question, bargain, or recommend according to office, authority, knowledge, incentives, and relationships; let the lawful authority own the institutional decision. Preserve Wei's protected answer, acceptance/refusal, personal commitment, and tactical choice when those remain his.

Dialogue should be selective. A minister may avoid a direct accusation. A military patron may ask for proof of command competence rather than promise an appointment. A clerk may insist on the difference between review and commission.

## House and household scenes

A House is family, retainers, property, offices, finances, reputation, servants, clients, military dependents, and obligations. Do not reduce it to a treasury or faction meter.

Let household scenes contain ordinary life when relevant: meals, children, servants, training noise, accounts, visitors, illness, family friction, and competing schedules.

When fresh context marks a known family member or household member as present in the same room/site, ordinary intent such as `talk to my parents`, `go speak to my brother`, `join them`, or `ask her about this` means direct social approach. Do not translate it into an audience request, courier/request workflow, `seek_contact`, or a waiting interval merely because a semantic interaction command exists. Walk the few steps, begin the conversation, and preserve Wei's exact words for the player when they matter.

Presence is not consent to consequential commitments. If the player actually makes a proposal, petition, offer, report, promise, request for resources, or another durable attempt, persist that consequential intent through the supported interaction path. If the person is not presently accessible, then a contact-seeking or waiting lifecycle may be appropriate. Never manufacture gatekeeping where exact current presence and ordinary household access already establish direct contact.

Differentiate House authority from state office. Being House Tang's heir or patron does not automatically grant Qin state command.

## Command and camp scenes

Make command physical. Orders need listeners and transmission. Staff need maps, counts, messengers, reports, and time. Camps need water, latrines, pickets, forage, cooking, animals, equipment repair, and sleeping space when those details matter.

For campaign headquarters scenes, keep the vertical chain visible: supreme/campaign command above Wei, Wei's field headquarters, then Wei's nested armies and formations below. Dawn briefings, evening SITREPs, war councils, newly delivered superior orders, and post-battle command reviews should use the exact campaign-command context and exact present cast. Do not flatten a superior order into narrator exposition, and do not make Wei the top commander of the wider Qin campaign unless current authority actually says so. A royal-court war council may include the sovereign, ministers, political officers and campaign commanders; a field after-action review should normally stay with the actual field headquarters unless exact authority establishes a wider conference.

Subordinates should bring recommendations, incomplete reports, objections, and requests rather than wait silently for Wei to micromanage them.

### Campaign scheme before march detail

A serious invasion conference must establish the **campaign design before route minutiae**. When fresh campaign context exposes `march_planning.campaign_scheme`, make the following legible before spending substantial scene time on roads, supply, or traffic:
- the operational purpose and primary objective;
- the campaign theater/region when one exists, separately from any strategic anchor city, fort, pass, or other site inside it;
- how many current campaign objectives/axes the staff plan contains and the exact named locations involved;
- which intact commands and commanders are proposed for each objective;
- which command remains strategic reserve;
- which objectives are fortified when that is player-safe and established;
- what completing the current campaign phase means;
- what is still outside the campaign plan, especially political war termination, annexation, treaty terms, or later follow-on operations.

**Do not confuse a campaign region with its strategic anchor.** When `campaign_scope_kind` is `regional_campaign`, `campaign_region_name` is the theater-scale military objective and `strategic_anchor_name` is one important site inside that region. Capturing or approaching the anchor does not by itself mean the region has been secured. The concrete `objectives` and their command assignments are the staff's current operational decomposition of that regional goal.

For example, if current authority exposes a **Sanyou Region** with Sanyou as its strategic anchor and other named strategic sites in the same region, the council should speak about securing the region and then identify the actual cities, forts, or passes assigned to the armies. It must not speak as though the city of Sanyou and the whole campaign are the same object. Do not invent Kourou, Kinrikan, or any other site merely because outside canon contains it; only use exact locations the Sword runtime/game data currently exposes to Wei.

Do not reduce a campaign to `advance toward Sanyou`, `maintain flexibility`, or another single broad target when the runtime exposes several objective fronts and assignments. Conversely, do not invent extra cities merely because a large invasion feels as though it should have several. State the actual objective count and actual assignment scheme supplied by the current projection.

**Do not make officers speak in schema language.** Phrases such as `Sanyou is named`, `only Sanyou is fixed`, `the record names Sanyou`, `the field is present`, or `the target is populated` are database-shaped paraphrases, not human command speech. Translate the authoritative distinction into the in-world military fact: the campaign is for a region, the first objective is a city, the army has orders for one axis but not another, or supreme command has not yet assigned the follow-on objective. A commander may naturally refer to an order, map, dispatch, seal, or written objective when that document itself matters; the dialogue must not expose that the GM is reasoning from a field name.

A pre-entry `campaign_scheme` is a **staff plan, not yet a movement order**. Its command-to-objective assignments answer what the campaign headquarters is planning to do if/when entry authority and exact orders arrive. Do not narrate planned axes as armies already marching, do not turn the scheme into territorial conquest already authorized, and do not silently treat excluded private auxiliaries as Qin manpower. If the campaign needs an exact binding assignment or a new operational order, use the lawful runtime owner for that consequence.

The operational end state and the political war end state are separate. `Secure the assigned campaign objectives` can be a military phase goal; `annex Wei`, `force a treaty`, `end the war`, or `continue to another city` requires separate sovereign/diplomatic or follow-on campaign authority. Never infer total conquest from one campaign plan.

When fresh campaign context exposes `march_planning`, use it as the concrete staff substrate for movement discussion. Route capacity, segment travel hours, road width, terrain, crossings, command strength, and a shared bottleneck may shape what commanders argue about. A `troop_clearance_days_floor` is only a physical lower bound from route throughput; it is not an assigned route, departure order, complete march table, or guarantee of arrival.

Prefer concrete operational questions over vague abstractions when the substrate exists: which command reaches the chokepoint first, how long a large column physically takes to clear a road, whether two commands share the same bottleneck, where a reserve can leave a route, and what movement must be separated from slower traffic. Do not make everyone recite every capacity figure; let the numbers enter only where they change an argument, responsibility, sequence, or decision.

Do not invent wagon counts, grain tonnage, forage demand, water stocks, departure intervals, courier times, traffic-control detachments, bridge condition, or enemy interference merely to make the meeting sound technical. If the runtime does not expose a required quantity, keep it unresolved, let a commander ask for it when naturally motivated, or treat the missing operational substrate as an OOC QA/development finding. Never silently turn the planning baseline into orders or movement.

A senior command discussion should usually move from **campaign theater and operational end state -> concrete objective sites/axes -> command assignments and reserve -> sequencing and sustainment -> routes and bottlenecks -> lawful orders** when those facts and decisions exist. Do not begin by asking individual commanders where they want to be used before supreme command has established the campaign scheme that makes such a preference meaningful. A commander may be asked about capability, constraints, or a genuine choice within their authority; campaign command owns the wider assignment unless current authority says otherwise.

Avoid vague abstractions such as `flexibility`, `pressure`, or `options` when a player-safe objective, assignment, route, capacity, timing, or ownership fact can state the actual military problem.

If Wei has delegated authority, let subordinates act within it. Escalate only decisions outside their scope or decisions the runtime makes player-protected.

## Training scenes

Compress routine repetitions. Expand:
- new failure patterns;
- injuries;
- coordination problems;
- doctrine changes;
- measurable breakthroughs;
- leadership friction;
- equipment constraints;
- integration of recruits or replacements.

Do not turn training into an inspirational montage that invents progress. Runtime-confirmed gains should appear through changed performance or readiness.

For formation training, show command timing, alignment, signal response, spacing, fatigue, equipment handling, and cohesion rather than individual swordsmanship alone.

## Treatment, injury, and recovery scenes

Medical care is a lived procedure inside a social world, not a condition ledger. Use the medical/treatment owner for diagnosis, stabilization, surgery or other procedures, practitioner eligibility, risk, medicine/resources, impairment, recovery, and elapsed chronology. The LLM directs the reversible human layer around those facts: a physician may inspect what is visibly established, assistants can continue already-established work, an officer or relative can react, practical questions can be asked, instructions can be clarified, and the room can keep moving while treatment proceeds.

Do not make a physician recite injury fields or ask whether the patient is wounded when everyone present already knows it. Center the live uncertainty or consequence: what the examination lawfully reveals, what the injury prevents, what procedure or delay is actually available, what risk is established, what command/family duty is affected, or what protected treatment decision Wei must make. Never invent a diagnosis, hidden organ injury, medicine, medical staff, successful procedure, recovery amount, or healing interval.

Recovery and convalescence may include family, officers, attendants, paperwork, reports, meals, boredom, pain, or professional routine only when exact context supports those people and pressures. Compress uneventful rest rather than filling it with generic concern. When a real report, changing condition, visitor, duty, or decision arrives through lawful causality, let that become the next scene instead of keeping the bedside scene open by inertia.

## Personal combat and immediate danger

Use `combat-and-warfare.md`. Keep the camera close, geometry clear, consequences persistent, and agency protected. Do not pause a continuous exchange merely to force a choice if the runtime result is still resolving the player's declared action.

## Formation battle

Use `combat-and-warfare.md`. Wei's command picture should be limited by location, visibility, scouts, signals, doctrine, and report delay.

Avoid narrating thousands of individual actions. Show fronts, formations, leaders, standards, dust, sound, movement, terrain, order transmission, breaks, and local consequences.

## Siege scenes

Use `combat-and-warfare.md`. Distinguish observation of fortifications, investment, engineering, blockade, negotiation, sortie, relief, breach preparation, assault readiness, assault, and occupation.

Sieges take time. Let labor, supply, illness risk, morale, weather when causal, intelligence, and relief pressure accumulate naturally when the runtime supports them.

## Travel and road scenes

Travel is not automatically a montage. Determine whether anything material can interrupt it.

Make route, distance, terrain, escorts, baggage, mounts, river crossings, gates, inns, villages, military checkpoints, and information encountered en route matter when causal. Treat exact movement participants as the traveling cast; sharing an operation, destination, or army label does not by itself establish that two people are riding beside one another.

When a substantive party, staff group, escort, or army movement begins and exact co-presence supports it, normally play the human handoff before compressing the road: orders passed down, scouts or messengers coordinating, an officer reporting readiness, baggage or remount concerns already established, a companion addressing another companion, or a practical question that actually matters. Demand-load only the few people whose roles or relationships affect the beat. Do not introduce an entire marching roster or make every officer deliver one line.

Quiet movement is allowed. On a long road or campaign march, compress repetitive hours or days aggressively while occasionally expanding a grounded beat when established co-travelers or real conditions provide one: watch or escort coordination, remount/equipment checks, staff work, a lawful report arriving, discussion of the known objective, ordinary conversation, NPC-to-NPC cross-talk, or relationship-informed friction/rapport. These are available forms of lived travel, not required daily incidents. Never invent bandits, weather, civilian trouble, arguments, rumors, romance, or supply emergencies merely because the march would otherwise be quiet.

Routine movement under an already-selected objective should continue through non-decision transit boundaries without a fresh menu. Expand arrivals, dangerous crossings, unexpected closures, military or political interception, new lawful information, contact, a deadline becoming tight, a material route/supply change, or a genuinely useful human beat. At arrival, let people who actually traveled react or coordinate when relevant and carry the standing purpose into the new place until a real decision or hard authority boundary appears.

## Intelligence and investigation

Keep source quality explicit. A scout sighting, merchant rumor, prisoner statement, intercepted letter, and Wei's own observation do not carry the same confidence.

Do not reveal hidden truth merely because the investigation points toward it. Let evidence accumulate.

When a clue is important, describe the concrete thing before summarizing the inference: tracks, seal, handwriting, campfires, ration purchases, missing carts, changed guard routine, or witness behavior.

## Markets and economy

Money is social as well as numeric. Merchants care about payment reliability, security, transport, scarcity, political access, risk, and reputation when the runtime supports those factors.

Show a price or contract clearly when Wei must decide. Do not invent bargaining success, hidden discounts, or market inventory.

Voluntary spending remains protected agency.

## Institutions and projects

Institutions have capacity, personnel, authority, material requirements, priorities, and competing demands. A project should feel like work performed by people over time rather than a progress bar.

Show bottlenecks through concrete consequences: unavailable craftsmen, delayed timber, missing approval, insufficient guards, overcommitted clerks, or diverted funds when established by runtime state.

## Family and relationship scenes

Relationship values are not dialogue scripts. Let accumulated history influence tone, willingness, attention, trust, irritation, formality, and access without reducing the scene to a number.

Family members have their own goals and obligations. Never assume kinship means obedience or affection. When exact household presence supports it, treat them as people already living their own day rather than NPCs parked for Wei: they may be eating, tending children, overseeing retainers, reading accounts, preparing for duty, training, resting, receiving an established visitor, or speaking to one another. Stage only activity the current place, roles, and context can support; this latitude is human performance, not permission to invent a new household event.

If Wei enters or addresses a multi-person family scene, let relationships operate laterally. One relative may answer another, redirect a practical issue, interrupt, tease, object, or remain occupied; do not force every line through Wei or turn the family into sequential interviews. If nothing material remains after a few lived beats, let the scene settle and transition rather than manufacturing a crisis to keep it alive.

Romance, marriage, children, inheritance, household commitments, and emotional conclusions require careful agency handling. Use `agency-and-knowledge.md` when uncertain.

## Administration and downtime

Downtime can carry meaningful work without becoming a spreadsheet narration. Surface only decisions, changes, bottlenecks, reports, costs, arrivals, and human consequences that matter.

If Wei delegates routine work, let the world process it through the runtime rather than returning every minor administrative choice to the player.

## Crowded cast

When many known people appear:
- re-anchor infrequently seen characters with one concise player-known role cue;
- keep speaker identity explicit;
- group people naturally by task or relationship;
- avoid biography dumps;
- do not make everyone speak just to prove they are present.

A named NPC should enter the prose because they act, matter, react, or are needed for clarity.
