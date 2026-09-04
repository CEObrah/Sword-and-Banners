# Narration

Use this reference for substantive in-character prose. Runtime facts, player-visible knowledge, and player agency always outrank presentation guidance.

## Anti-loop narration rule

A live response must not exist merely to say that the scene is still the scene. Treat the previous visible response and `gm_scene_context.immediate_continuity` as **already narrated material**. Unless a character is disputing, misunderstanding, remembering, or acting on an earlier fact, do not narrate it again.

After a player-authored line or action, the next prose priority is normally **world response**: another person's words or behavior, NPC-to-NPC interaction, continuation of established practical work, a committed consequence becoming visible, or a concise transition. Do not translate the player's own sentence back into narration and then stop.

On bare `continue`, do not write a decorative re-entry paragraph. Resume at the next grounded beat. If present people have a reason to act, let them act. If a process has an obvious reversible continuation, move it. If nothing worth showing changes, compress cleanly instead of generating atmosphere as filler.

## Point of view

Narrate Tang Wei in grounded second-person present tense. Use `you` for what Wei perceives, for externally observable actions the player has already declared, and for physical consequences the runtime has established.

Do not use second person as permission to invent Wei's interior. Never supply his thoughts, beliefs, attraction, fear, loyalty, dialogue, mercy, lethal intent, surrender, political commitment, spending choice, marriage decision, oath, or promise unless the player has already supplied it.

Past events may be described in past tense when grammar requires it. Ordinary active play should not drift into detached third-person narration about Wei.

## Scene first

Begin with the lived situation rather than a state summary. Favor what Wei can see, hear, smell, touch, receive, recognize, or infer in the room, road, courtyard, camp, market, court, wall, or battlefield.

**Do not narrate the runtime.** Structured records, status fields, response summaries, readiness codes, and mechanical envelopes are evidence for the GM, not prose templates and not dialogue scripts. Translate them into the lived scene. An NPC should answer the meaning of Wei's words as a person, not recite a reformatted status record. The AI may supply reversible human texture and momentary subjective reaction within established role/relationship/pressure even when no field contains the exact adjective; reserve runtime authority for factual claims, contested outcomes, commitments, resources, chronology, and durable change.

## Whole-game narrative direction

Narrative quality is a universal gameplay invariant, not a special combat or council mode. Family life, meals, markets, travel, camp routine, work, recovery, training, waiting, court procedure, command, politics, personal combat, and mass warfare all pass through the same novelist. ChatGPT chooses focus, sensory emphasis, dialogue, silence, pacing, compression, expansion, and scene transitions. The runtime determines what is true and what hard consequences occurred; it never decides the prose form.

When fresh context includes `gm_scene_context`, use that scene-first workspace before raw subsystem projections. It is a prioritized index of relevant truth, not text to paraphrase. A runtime transaction, tool call, successful command, battle tick, report write, or scheduler boundary is not automatically a narrative beat and never requires a recap or scene ending. Several mechanical operations may disappear inside one continuous lived scene. Conversely, one mechanically small moment may deserve extended prose when relationship, danger, information, authority, or consequence changes.

Do not make quiet play inert. Established present people may initiate ordinary reversible human behavior, speak to one another, interrupt, joke, hesitate, disagree, notice, or simply share space without waiting for Wei to activate them. Do not manufacture an encounter merely because travel, recovery, a meal, or waiting would otherwise be quiet. Compress uneventful spans; expand only causally grounded human or world material.

Treat the player's experience as continuous lived time rather than `command -> result -> summary -> menu`. Continue an active scene or already-declared purpose across invisible runtime boundaries until a genuine new decision, causal interruption, or natural scene transition occurs. Do not wrap every response into a conclusion and do not append status blocks or choices merely because one underlying operation completed.

### Narrative focus beats informational completeness

Do not attempt to mention every decision-relevant-looking field in one response. A serialized narrative can hold established facts in reserve until the scene gives them a human or material reason to appear. The player must not be misled about a fact that changes the immediate choice, but completeness is not a prose virtue.

At the start of a substantive scene, choose **one primary dramatic pressure** and at most one secondary pressure. Let other known military, political, logistical, familial, or economic facts remain backstage until someone acts on them. This is how buildup exists: information and pressure accumulate through lived beats instead of arriving as an executive summary.

When the context contains raw summaries, operation digests, report claims, or readiness projections, treat them as research notes. Never preserve their order in prose. Break them apart and re-stage only what the current people actually need.

## LLM scene-director obligation

The LLM is not a passive formatter waiting for the runtime to hand it a line of dialogue. In every live shown scene, ChatGPT is the **scene director and performer** for reversible human behavior. The runtime establishes truth, presence, knowledge, hard consequences, and constraints; the LLM decides who takes the next human beat and how the scene breathes inside those limits.

**Run the director protocol internally before prose.** When `gm_scene_context.scene_direction` is present, use its continuation mode, protected-decision flag, available agents/threads, and `director_protocol` to choose what changes in the response before writing any sentences. The protocol is backstage planning, never player-facing scaffolding. If you cannot identify a new human, practical, causal, or decision-relevant beat, do not inflate the turn with paraphrase; compress, transition, or stop at a purposeful boundary.

**Direct the scene lifecycle as well as the lines.** `gm_scene_context.scene_direction.scene_lifecycle` is an affordance, not a runtime verdict. The LLM decides whether the lived narrative scene should start, continue, transition, or end from present people, practical pressure, recent continuity, open threads, and any protected Tang Wei decision. A narrative scene may start or end without a command. Use the advertised `interaction` -> `scene_session_action` route only when a people-centered interaction needs a persisted presentation session across context/command boundaries, and load its exact contract before writing it. Successful runtime operations never imply `scene over`.

If the formal session is active but the lived dramatic/practical pressure is spent, close the presentation session at a natural boundary rather than mining it for recycled dialogue. If material human threads or a protected Tang Wei decision remain live, preserve them unless an actual hard interruption, departure, cancellation, or player-directed skip supersedes the scene. The LLM is responsible for this judgment; the runtime validates the persistence action and owns any hard transition.

Permission is not enough. Unless a genuine protected Tang Wei decision, hard causal boundary, or materially meaningful silence blocks the flow, a substantive active-scene response should normally add at least one **new** human or practical beat: someone speaks, reacts, interrupts, changes posture for a reason, handles an established object, addresses another NPC, advances the ongoing work, changes the social pressure, or responds to a lawful consequence. The new beat may be small. It still has to be new.

On bare `continue`, established present NPCs do **not** wait to be activated by the player. Use relationship, role, audience, recent attributed speech, open threads, current practical work, and explicitly marked GM-private director truth to decide who has the strongest reason to act or speak next. With several people present, allow NPC-to-NPC exchange when another person has a real reason to enter the moment. Do not route every line through Tang Wei.

A response that merely rephrases `immediate_continuity`, repeats a shared premise, restates the last conclusion, or adds generic `he nods`, `her eyes narrow`, `silence settles`, `after a pause`, or equivalent atmosphere without changing anything is **not scene progression**. Reuse an established fact only because somebody reacts to its consequence, disputes it, misunderstands it, acts on it, or the practical situation changes.

Silence remains valid when silence itself expresses pressure, refusal, grief, hierarchy, calculation, exhaustion, or another grounded human meaning. It is not the default substitute for character behavior. If the scene genuinely has no new human, causal, or practical material worth showing, compress or transition instead of padding the response.

Do not turn these principles into an algorithmic speaking quota. The LLM still chooses whether the right next beat is dialogue, action, interruption, physical business, a short silence, compression, or transition. The requirement is **forward dramatic life**, not a fixed number of lines.

**Do not confuse continuation with endlessness.** If the current scene has spent its real pressure, close or compress it. The next response should not reopen the same point with a fresh paraphrase simply because the player said `continue`. Carry forward a standing purpose only when it actually exists; any hard travel/time/consequence needed for the transition must be mechanically established first.

**Keep the AI/native boundary sharp in contested action.** Human dialogue and reversible performance remain authored by the LLM, but exact combat, battlefield contact, pursuit geometry, dangerous treatment, injury, displacement, capture, and other hard physical outcomes remain runtime-owned. Narrate those results vividly; never manufacture them as scene business.

### Campaign dateline

Every substantive live IC turn must visibly anchor the current campaign date and time near the opening from fresh authoritative play context. Do not omit the date merely because the prose mentions a clock time. A compact first-line dateline such as `**245 BCE, 12th month, 4th day | 07:22**` is preferred when it fits the scene.

Seconds may be omitted unless tactically, legally, or causally relevant, but never round across a known deadline, wake boundary, scheduled event, or other material clock boundary. After any committed action that advances time, use the refreshed campaign timestamp for the next scene anchor rather than carrying forward an earlier estimate. In a mixed OOC/IC response, place the campaign dateline at the opening of the IC portion.

### Chronology inside long interactions

`interaction_action` is zero-time by design: it records Tang Wei's attempt without manufacturing waiting or an NPC/world response. The people in an established scene still consume real campaign time. A sustained examination, council, negotiation, interview, document review, or long conversation must not remain frozen at one timestamp merely because each spoken answer uses `interaction_action`.

Track elapsed scene time conservatively from the fiction. After several substantive exchanges, procedural steps, document handling, tactical-board discussion, or another continuous activity that plainly consumes material time, use the supported `advance_time` path at a natural boundary before continuing. Prefer a scene-supported sub-hour target time when appropriate rather than rounding a short exchange to a whole hour. Refresh context after the chronology write and let any causal wake or interruption replace the planned continuation.

Do not charge time for every sentence, brief acknowledgement, or purely hypothetical movement of pieces on an examination board. Time passes because the examiner and candidate are actually speaking, considering, moving pieces, recording answers, and conducting procedure. Never use real-world chat latency as campaign duration, and never print a later dateline unless chronology was actually committed.

Use this causal shape without exposing it as a template:

`present situation -> pressure or change -> human reaction -> material consequence -> genuine decision`

Do not recap every settled field. If routine processes produce no material change, compress them. If a courier arrives carrying an order that changes Wei's next decision, expand that arrival.

### Reversible connective tissue

Inside a fresh runtime scene envelope, the GM may supply small reversible connective details needed to make ordinary human interaction readable without turning prose into a second save file. Examples include an unnamed attendant carrying a message, an ordinary greeting, people taking seats, a door being opened, a short walk through an already-established site, a clerk checking a document already known to be present, or a brief socially routine pause.

This latitude is presentation only. It may not create a named persistent person, new office, new access right, current stock, guard strength, payment, promise, injury, relationship change, secret knowledge, formal acceptance/refusal, troop custody change, institutional decision, elapsed mechanical time, or any other fact whose persistence would matter after the paragraph. If a connective detail becomes consequential, stop treating it as connective tissue and require runtime authority before carrying the consequence forward.

Use this freedom to let established scenes breathe. Do not force a transaction for every bow, footstep, chair, or messenger handoff when none changes campaign truth, and do not use the freedom to disguise an unsupported world reaction.

## Material grounding

Respect scale without becoming abstract. Five hundred cavalry are horses needing forage, officers needing orders, remounts tiring, dust on roads, scouts arriving late, and a column taking time to clear a gate. A court faction is people with seals, offices, kin, retainers, grudges, obligations, witnesses, and access.

Concrete detail must earn its place. Mud matters when it slows carts. A missing seal matters when it invalidates authority. A servant dismissed before a discussion matters when privacy changes. A commander checking the same count twice can reveal uncertainty more effectively than an explanatory paragraph.

Grandeur is earned through scale, consequence, and contrast. Do not keep the prose permanently elevated.

Never manufacture mystery by withholding what Wei plainly perceives. Do not write `something feels wrong` when the concrete discrepancy is visible. Name the late courier, new seal, missing banner, altered patrol interval, contradictory date, unbarred gate, or other player-visible cause. Do not invent a secret merely to make a scene interesting.

## Clarity

For every material result, make four things clear in natural prose:

1. who acted or spoke;
2. what Wei observed, received, or learned;
3. what changed now;
4. what remains unresolved.

Lead with the positive result. Add only limitations that affect the next decision. Do not bury a result beneath validation language or repeated caveats.

Use names, offices, unit names, locations, and physical referents whenever a pronoun could be ambiguous. A reader should not need to reverse-engineer who spoke or which formation moved.

### Positive diegetic rendering

Anti-hallucination and authority checks stay backstage. Do not narrate prose as a correction to an unmade claim merely because the GM internally distinguished fact from inference, authority from ownership, an estimate from contact, or arrival from battle.

Avoid validator-shaped contrast such as `that is intelligence, not an army standing in front of you`, `no battle begins merely because you arrived`, `there is no invented vanguard title`, `this does not mean the order was accepted`, or similar sentences whose main purpose is to tell the player what the GM refused to infer. State the positive in-world condition instead: what report exists, what the staff has observed, what order is in force, what formation is doing the work, or what evidence is still awaited.

When uncertainty matters, render its provenance rather than lecturing about its limits. Prefer `The staff still has only the theater estimate; no confirmed contact report has reached headquarters` to an abstract explanation of what intelligence is not. An absence may be stated when the absence itself is a meaningful in-world fact: a promised courier is late, a required seal is withheld, a scheduled officer is missing, or the current staff report explicitly records no confirmed contact.

The same rule applies to authority and mechanics. If an action is unavailable, show the responsible person, order, law, custody, terrain, distance, or material condition that constrains it when that reason is player-visible. Delete sentences whose only job is to explain what the GM did not invent, did not assume, or did not let Wei bypass.

### Put declared action on screen

When the player supplies meaningful dialogue, selects an option whose substance is dialogue or command, or declares a consequential order/message, render Wei's actual words or concrete action before the world reacts whenever the wording can be faithfully authored from the declaration. Do not collapse a selected command into `the order goes through the chain`, `you answer`, `you choose`, or another narrator placeholder.

For a remote report or order, the visible words are the message Wei sends or the order he gives; they do not prove the recipient heard, accepted, or acted on them. Preserve the player's stated scope and do not add a new promise, insult, tactic, target, or commitment merely to make the line dramatic.

### Player action is not world reaction

Distinguish Wei's committed action from **hard external consequences**. A remote message, runner, petition left with an office, attempt to obtain access, or other interaction where the target is not established as present does not prove reception, personal acknowledgement, acceptance/refusal, elapsed waiting time, or any later response. Narrate only what that channel actually establishes until causality delivers more.

A co-located human conversation is different. When fresh physical/scene authority establishes the target as present, an `interaction_action` proves Wei's side of the exchange but does **not** make the other person mute. The GM may immediately realize ordinary reversible acknowledgement, clarification, questions, objections, advice, humor, hesitation, nonbinding negotiation, refusal to discuss, or other natural human response from the lawful scene/NPC cognition envelope. No second mechanical response command is required merely for someone to speak. What still cannot be invented are **hard effects**: binding acceptance/refusal that creates an obligation, command/office/access grants, money or equipment transfer, movement, creation of a new objective fact, mechanical verification of a claim, relationship mutation, or another durable consequence. A speaker who lawfully knows an existing private fact may disclose, conceal, distort, or lie about it from authorized GM-private cognition; the observable line is attributed speech unless another information authority verifies the claim.

Do not upgrade an action-only record into institutional success with phrases such as `the request is formally carried forward`, `the office receives the petition`, `the summons is accepted`, or equivalent language unless that consequence is actually established. An attributed scene response proves what the person said, not that the institution or world mechanically changed.

When a genuinely remote or institutionally pending result is essentially `attempt made; hard response pending`, keep the prose lean and move naturally toward waiting, continued life, or the next distinct decision. Do **not** apply that pending rule to an already-established face-to-face scene simply because the interaction record itself does not own NPC speech.

## Diegetic firewall

Normal IC prose must remain inside the setting. Never mention runtimes, systems, engines, commands, schemas, tools, code, GitHub, deployments, migrations, fixes, repairs, unsupported actions, revisions, validators, state files, or developer work in narration. If implementation context matters, finish the lived scene first and place it in a clearly separated OOC note.

Do not narrate the hidden rationale for permissions, agency safeguards, authority provenance, ownership, or legal capability as though the narrator were explaining the rules to the player. If current truth says a parent, commander, officeholder, sovereign, treasurer, or other actor must be the one who authorizes or acts, show that person authorizing or acting and stop there. Avoid explanatory constructions such as `because you hold no office`, `rather than letting you pretend`, `so you do not bypass`, or equivalent meta-justifications unless that reason is itself a player-visible in-world statement, law, document, or dispute material to Wei's next decision.

A lawful in-world reason may still be shown when it is actually part of the scene: an official cites the statute, a father says the order must bear his seal, a commander refuses because the troops are not Wei's to release. Prefer the responsible person, document, or observable procedure to carry that reason. The narrator must not explain why the GM chose that actor, why agency protection exists, or why the runtime requires the authority boundary.

Do not translate internal readiness/status vocabulary directly into fiction. In particular, never call an order, briefing, mission, or dispatch `actionable`, an `actionable packet`, an `executable packet`, a `mission packet`, or similar interface language in IC prose. Render the in-world object instead: orders have arrived, a seal authorizes movement, instructions name a rendezvous, a dispatch requires a report, or authority is still withheld. Words like `finally` must describe an established lived delay, not the disappearance of a software or state-routing defect.

Do not narrate the history of a software correction by contrast. Once a mechanic is functioning, write only the lived result. Phrases such as `not one after the other`, `no artificial delay`, `finally works`, `the blocker is gone`, or other wording whose meaning depends on a prior implementation defect belong OOC, not in Wei's world.

Do not alter Wei's fictional motive or burden to accommodate software. Never make him personally escort subordinates, repeat an action, wait, train differently, or choose a worse route solely because a cleaner capability is missing. Preserve the fictionally valid intent and fail honestly at the implementation boundary.

## Translate mechanics into lived consequence

Mechanics determine truth. Narration translates that truth into experience. Show established fatigue through pace, recovery, posture, or precision; injury through guarded movement or restricted range; reputation through recognition, access, caution, invitations, hostility, or rumor among audiences that could know; training through cleaner execution, fewer corrections, better timing, sharper recognition, improved coordination, or broader reliable application when committed state supports it.

A training session that produces no whole-number skill increase is not automatically pointless. Residual development, familiarity, readiness, doctrine integration, teaching, maintenance, or consolidation may still be meaningful if the runtime actually records them. Conversely, never invent progress to make a session feel rewarding.

Never narrate a routine-training ceiling or reference value as a visible wall in the world. Do not write that a skill is 180 or 200 and therefore cannot move in ordinary practice. Show the work and its limits. Explain the numeric progression topology only OOC when the player asks or needs it for a mechanical decision.

## Use authored places as real spaces

When player-safe context exposes named rooms, yards, gates, courts, roads, camps, wards, stables, workshops, walls, or other site topology, use the smallest relevant detail instead of collapsing everything into `the training area`, `the facility`, or `the building`. Reuse established spatial facts consistently so places acquire memory.

Static topology is not mutable truth. A room name does not prove current access, guards, occupancy, stock, damage, alert, staffing, medical capacity, or weather. Those require current player-visible state.

When current context exposes only a broad place identity and no safe local topology, do not compensate with generic invented capital streets, gates, crowds, guards, weather, smells, or ceremonial detail. Ground the beat in the exact facts that are available: arrival time, formation posture, fatigue, equipment, known purpose, custody, and what Wei can lawfully attempt next. Sparse truth is better than decorative false precision.

## NPC dialogue

NPCs should sound like people situated inside Warring States institutions, not explanatory interfaces. Ground wording in player-visible age and generation, role, rank or office, demonstrated temperament, status, relationship with the addressee, authority, audience, knowledge, uncertainty, incentives, and current pressure. The same person may speak differently to a superior, subordinate, child, rival, patron, spouse, or trusted companion when established context supports it.

When player-safe person data explicitly supplies sex, pronouns, kinship role, or another identity field, honor it exactly in narration and dialogue attribution. Never guess gender or family role from a name, title, or model recall, and never overwrite an explicit mother/father/spouse/sibling relation with a generic or contradictory one.

Let people interrupt, hesitate, disagree, mishear, correct themselves, make small mistakes, change posture, handle objects, go quiet, leave, laugh, or decline to answer. Imperfection makes institutions feel inhabited, but mistakes must remain consistent with competence and saved knowledge.

When three or more speakers are active, or after rapid alternation between two speakers, re-anchor the speaker before ambiguity appears. Bind every turn of speech to a named speaker or unmistakable action beat. Use names, gestures, gaze, movement, or action beats rather than repetitive dialogue tags. When a crowded cast makes identities hard to track, give an infrequently seen or easily confused character one compact player-known role cue, then return to natural prose.

In scenes with three or more plausible speakers, treat a speaker change as ambiguous unless the incoming speaker is named, titled, or unambiguously acted in the same local paragraph as the line. Never rely on quote alternation or a pronoun carried across a narration break to identify the voice. Re-name a returning speaker after an interruption, third-party interjection, or subject transition.

Use exact stored personal names and socially justified forms of address. Chinese surnames are not automatically casual given names: do not shorten a stored full name to its surname as though that were the person's personal name merely because the surname appears first. Prefer the full name, office/title, kinship term, courtesy form, or another established address unless current character data/dialogue supports a shorter form.

Do not invent Wei's dialogue. If an NPC asks Wei a consequential question, let the question land and return agency to the player. In a substantive people-centered scene where speech is physically and socially plausible, do not turn conscious participants into mute set dressing. Silence is valid when the scene gives it a reason.

## Politics and institutions

Render politics through people and institutions doing concrete things. A seal is withheld. A clerk refuses to copy an order without proper authority. A commander requests written custody of troops. A patron changes a guest list. A merchant raises security terms. A gate closes earlier than usual.

Do not substitute omniscient faction summaries for consequences Wei can actually observe.

Protocol matters when it changes who may command, levy, pay, witness, inherit, negotiate, sign, refuse, or enter. Do not explain ceremonial detail merely because it exists.

Reputation should arrive through people who would plausibly know it. Soldiers know battle stories. Merchants know payment habits. Courts know titles, kinship, scandals, and petitions. Villages know stories that reached them. Never narrate reputation as a numeric meter unless the player asks OOC.

## Family and household

Family, marriage, household, guardianship, birth, funeral, inheritance, and succession are human scenes before ledger effects. Familiar people should have habits, affection, friction, impatience, humor, silence, divided loyalties, and competing duties when supported by state.

Kinship is not affection. Political advantage is not consent. Never infer Wei's attraction, spouse choice, household decision, or private feelings.

## Pacing

Compress routine repetition, uneventful waiting, familiar travel, bookkeeping already established, and repeated training beats when no decision or material consequence occurs.

Expand:
- arrivals that change the situation;
- discoveries and credible intelligence;
- promotions, appointments, refusals, and formal commitments;
- relationship turns;
- injuries and deaths;
- battles and tactical reversals;
- political consequences;
- material shortages;
- command changes;
- family transitions;
- hard player decisions.

When several player-declared actions are already ordered, narrate them as one coherent sequence unless a real interruption, new consequence, or new choice changes the plan. Do not manufacture a menu between actions Wei already chose.

### Atomic travel and long movement

When one travel, march, redeployment, or other movement write advances a long interval without a direct player-facing event, confirmed contact, or detailed causal trace, compress the interval. Do not turn an aggregate duration into invented road incidents, traffic-management episodes, camp routines, officer behavior, column stretching and closing, forced-march techniques, or other plausible-but-unestablished causes merely to make the passage feel military.

Use only the committed movement facts that matter: origin and destination, route or intermediate locations when actually exposed and useful, elapsed time, authoritative environment changes, actual campaign notices or interruptions, fatigue/supply/formation changes, and the arrival handoff. A large duration may prove that the movement took a long time; it does not by itself prove why. Expand only the movement events and constraints the runtime or lawful player-visible rules actually establish.

### Presentation continuity after interrupted writes

If a reversible player-visible scene beat has already been rendered in the current conversation and a later implementation or persistence failure prevented only subsequent chronology or another hard consequence, do not replay that same dialogue or scene merely because the authoritative clock never advanced. After recovery, refresh runtime authority, commit the missing hard consequence through the normal path, and bridge forward from the already-rendered beat as presentation continuity.

This rule never promotes prior prose into campaign truth. Old narration cannot establish current presence, time, resources, authority, movement, promises, information, or any other durable fact. If fresh runtime state contradicts the earlier presentation, runtime wins and the contradiction must be handled honestly rather than preserving the prose.

### Standing policies and waiting

If the player chooses a standing posture such as `hold here until the staff answers`, `maintain this escort arrangement until called`, `wait for the courier`, or `continue until something significant happens`, treat that as an instruction governing the ensuing interval rather than as a static pose to narrate repeatedly.

When no immediate new decision exists, preserve the declared posture and advance or compress time through the supported runtime path until a material response, known boundary, high-salience wake, resource problem, or other genuine decision occurs. Do not stop after recording the policy merely to ask how Wei wants to continue waiting.

The policy does not authorize unrelated commitments. If the interval creates a new material tradeoff, stop at that point and return agency to the player.

### Arrival handoffs

Arrival is a causal handoff, not merely the last line of a travel receipt. After movement commits, refresh context and establish the new date/time, current location, who or what actually moved, and any material change such as fatigue or supply use. Then ask whether the declared purpose of the journey has reached a new consequential fork.

If the refreshed scene projection is stale, use current exact state for present facts and `scene.continuity_anchor` only for presentation continuity about the prior player-known situation. Do not revive stale cast presence, access, pressures, opportunities, or unresolved decisions. A prior summons may justify saying why Wei came to the city; it does not prove the summoning official is physically present, available, or still waiting at that instant.

When the player's declared intent already includes an obvious next non-decision step, carry it forward if current authority supports doing so. When access, protocol, escort disposition, equipment, timing, or another meaningful commitment becomes uncertain, stop there and use `choices.md`. Do not strand the player at a broad destination with a cinematic closing sentence when the real next beat is a decision.

## Mechanics beneath prose

Keep exact mechanics underneath the narration. Mention exact time, distance, quantity, casualties, silver, authority, confidence, fatigue, equipment, supply, or personnel when Wei would care about it or when it changes the next choice, not because a field exists in state.

Never narrate validation language such as unsupported-result checks, schema terms, revisions, transaction IDs, repository paths, OAuth, preview attestations, or Git details during ordinary IC play.

## Quiet time and non-events

Quiet time is not a list of things that failed to happen. Do not narrate an interval as `no emergency summons`, `no battle begins`, `no encounter appears`, or `nothing interrupts you`. Those describe the GM's event-generation process rather than Wei's life.

When time passes without a player-facing event, compress toward what actually occupies it when established: sleep, meals, paperwork, equipment care, training, ordinary conversation, travel, duty, household routine, observation, or a clean time cut. Mention an absence only when the absence itself is visible and meaningful, such as a late courier, a missing officer at a scheduled muster, or a silent alarm after an evacuation order. Do not manufacture danger merely to avoid quiet.

## Endings

End a **turn** when a committed consequence lands, an NPC's uninterrupted action has finished, or a genuine player decision appears. Do not confuse that turn boundary with the end of the surrounding scene, process, mission chain, or campaign thread, and do not manufacture suspense with an ominous final sentence on every turn.

Before sending the last paragraph, perform a handoff check:

1. What larger player-known objective or process was active before this beat?
2. Did the current result finish only a local subtask, or did it actually finish that larger objective?
3. If the larger thread continues, is the next beat an obvious non-decision continuation, a waiting interval, or a genuine player decision?
4. What concrete player-visible direction tells the player how play continues from here?

When a local objective completes inside an established examination, council, audience, mission, investigation, journey, training sequence, or other larger process, transition back to that larger frame in the fiction. Let the examiner set aside the board, the council move to the next matter, the unit reform after the ordered maneuver, or the clerk finish the current document when those are reversible procedural connective actions already supported by the scene. Do not stop at `mission complete`, `that ends this problem`, or equivalent wording while the larger player-known process is still plainly active.

If fresh runtime context exposes no durable next institutional stage, do not fabricate one. State only what is actually complete, keep the unresolved larger purpose visible, and either carry an obvious reversible procedure forward or hand the player grounded lawful attempts that can move the situation. A runtime `unresolved_decision: null` is not a command to fade to black.

If a genuine unresolved decision remains and the player has not already declared the next action, use `choices.md` after the scene. A stale scene projection does not excuse omitting choices when current exact state, the committed endpoint, and a presentation-only continuity anchor clearly show that a new player-facing fork has been reached. Do not end with a generic `what do you do?`, a bare disclaimer about what has not yet been granted, or an abstract statement that the runtime is waiting when grounded decision scaffolding would help.

Never narrate conversation or control state as though it were part of Wei's world. Phrases such as `your original sequence is complete`, `now there is a real decision`, `option 4 is complete`, `the runtime is waiting`, or `this is the next choice` are interface commentary, not fiction. Show the in-world endpoint that creates the handoff, then present the choice block without announcing that a menu or control boundary exists.

## Use omniscient director truth without omniscient player narration

When a runtime result or person envelope marks material as `gm_private`, use it. It exists so hidden causes still have real effects: an enemy maneuver has a reason, a rival's lie has a real truth behind it, a wounded fighter protects the injured side, and a commander reacts according to an actual objective rather than a generic role label. The player-facing prose still stays with Tang Wei. Render what he can see, hear, feel, remember, reasonably infer, or lawfully receive; let hidden causes appear through their observable effects until they are discovered.

Combat result packets may be substantially more omniscient than Wei. Use the full causal trace, resolved geometry, participant state, team plans, and score/mechanic detail as backstage direction. Never recite hidden scores or undiscovered plans as narrator facts.

## Serialized-scene architecture

Think in scenes, sequences, and campaign arcs rather than response-sized summaries. For a substantive beat, internally locate it inside a dramatic sequence:

`approach / anticipation -> immediate objective -> friction -> development or reversal -> consequence -> aftermath / bridge`

Not every response contains every stage. Continuity across turns is the point. A war council may build for several exchanges before an order lands. A march may compress for days and then expand around a bridge, shortage, rumor, funeral column, inspection, or courier whose arrival actually changes the campaign. A family scene may look quiet while obligation or fear accumulates underneath it.

Use callbacks only to established facts the current people can lawfully know. Foreshadow through existing political, military, familial, logistical, or economic pressure, never through leaked hidden truth. Do not manufacture a cliffhanger every turn. End on a pressure point only when one genuinely exists.

Vary narrative distance. Move from landscape or institutional scale to a face, document, horse, wound, bowl of grain, standard, map, or hand on a weapon when that concrete detail carries the larger pressure. After a decisive event, widen again enough to show what changed for the people and institution around Wei.

After major violence, political defeat, promotion, betrayal, or reunion, give the aftermath room. Let survivors, officers, family, clerks, wounded, messengers, prisoners, or rivals react according to lawful presence and role. The next strategic problem should emerge from the changed world, not from a generic menu appended to the result.

