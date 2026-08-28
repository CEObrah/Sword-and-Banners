# Scene Playbook

Use only the scene modules relevant to the current turn. These are craft guides, not separate mechanics.

## Court and political scenes

Make rank, audience, seating, seals, witnesses, introductions, precedent, patronage, kinship, and access matter only when they change leverage or authority.

Politics should appear as concrete behavior: who is admitted, who signs, who speaks first, who receives a copy, who is kept waiting, who must provide written authority, and who can safely contradict whom.

Do not narrate an omniscient faction map. Let Wei encounter political structure through people and consequences.

A formal royal-court event is not a private quest-giver conversation. When fresh runtime authority supplies a court session and exact `present_person_refs`, stage the relevant ruler, ministers, political officers, military commanders, and other established attendees as a real institutional room. Let materially relevant people react, question, disagree, witness, or clarify according to role. Do not force everyone to speak, and never infer attendance merely from office or broad capital co-location when the current event does not establish it. A field-headquarters council is narrower and should not drag the royal court into camp.

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

When fresh campaign context exposes `march_planning`, use it as the concrete staff substrate for movement discussion. Route capacity, segment travel hours, road width, terrain, crossings, command strength, and a shared bottleneck may shape what commanders argue about. A `troop_clearance_days_floor` is only a physical lower bound from route throughput; it is not an assigned route, departure order, complete march table, or guarantee of arrival.

Prefer concrete operational questions over vague abstractions when the substrate exists: which command reaches the chokepoint first, how long a large column physically takes to clear a road, whether two commands share the same bottleneck, where a reserve can leave a route, and what movement must be separated from slower traffic. Do not make everyone recite every capacity figure; let the numbers enter only where they change an argument, responsibility, sequence, or decision.

Do not invent wagon counts, grain tonnage, forage demand, water stocks, departure intervals, courier times, traffic-control detachments, bridge condition, or enemy interference merely to make the meeting sound technical. If the runtime does not expose a required quantity, keep it unresolved, let a commander ask for it when naturally motivated, or treat the missing operational substrate as an OOC QA/development finding. Never silently turn the planning baseline into orders or movement.

A senior command discussion should usually move from the concrete constraint toward sequencing, responsibility, reserves, sustainment, contingencies, and finally lawful orders when those facts and decisions exist. Avoid vague abstractions such as `flexibility`, `pressure`, or `options` when a player-safe route, capacity, timing, or ownership fact can state the actual military problem.

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

Make route, distance, terrain, escorts, baggage, mounts, river crossings, gates, inns, villages, military checkpoints, and information encountered en route matter when causal.

Compress uneventful known travel. Expand arrivals, dangerous crossings, unexpected closures, military movement, political interception, new information, or a deadline becoming tight.

## Intelligence and investigation

Keep source quality explicit. A scout sighting, merchant rumor, prisoner statement, intercepted letter, official dispatch, and Wei's own observation do not carry the same confidence.

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

Family members have their own goals and obligations. Never assume kinship means obedience or affection.

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
