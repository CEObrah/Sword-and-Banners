# Scene Craft and Human Presentation

Use this reference with `narration.md` for substantive people-centered scenes: family discussions, councils, audiences, command meetings, negotiations, briefings, institutional exchanges, camp conversations, training reviews, and other beats where the interaction itself is the scene.

## Prime rule: generate the scene, do not report on it

The runtime supplies truth. The prose should make that truth feel lived.

Do not turn structured context into a narrated status report followed by a token quote. Avoid this shape:

`state summary -> backend caveat -> one NPC line -> more caveats -> menu`

Prefer:

`small spatial frame -> human action/reaction -> several short exchanges -> concise narrator bridge -> genuine consequence or decision`

If the scene's purpose is conversation, dialogue and interaction should carry most of the beat unless silence, incapacity, separation, extreme urgency, or deliberate compression gives a concrete reason otherwise.

## Film-and-novel rendering gate

Substantive IC prose must pass a **movie/book test**: if the backend fields vanished and only the prose remained, the passage should still read like a lived Warring States scene rather than an explanation of what the simulation means.

Reject **structured-state paraphrase**. Do not walk through troop counts, confidence values, classifications, contact flags, authority boundaries, report provenance, operation status, or other structured facts one field at a time and then explain the semantic limitation of each field. Select the few facts that matter now and embody them in action: a courier arriving, a report being unrolled, an officer putting a finger on a road, a seal changing hands, men breaking formation, a commander going quiet over a casualty tally, horses standing blown after a hard ride.

The narrator is not an analyst standing beside the scene. Do not spend paragraphs explaining why a report does not prove intent, why an estimate is not contact, why a movement is not battle, why an order does not transfer ownership, or why a mechanic has not committed some other consequence. Keep those distinctions backstage unless a person in the world has a concrete reason to care about that exact distinction. Even then, let the character speak like a commander, clerk, parent, merchant, or courtier rather than a rules manual.

NPC dialogue must not be used to verbalize runtime disclaimers. A strategist may challenge an inference because he genuinely distrusts the evidence; he should not recite the simulation's caveat merely so the GM can prove it respected a knowledge boundary. Dialogue exists for agenda, judgment, pressure, disagreement, humor, fear, command, persuasion, and human response.

### Hard anti-briefing gate

The most dangerous failure mode is **polished briefing prose**: a dateline, generic weather, troop totals, a sequence of correct intelligence/authority distinctions, officers who verbalize those distinctions, then a large numbered menu. That shape is mechanically careful and narratively dead. Reject it.

For a command scene, prefer a shape such as:

`dateline -> concrete staff action or officer line -> another person pushes back -> one or two decision-relevant facts emerge through the exchange -> practical work continues -> pressure turns or sharpens -> Wei receives the actual decision`

Do not make the first several paragraphs perform orientation that the scene itself can perform. Do not state `that distinction matters`, `the question is`, `not because X but because Y`, or similar analyst narration merely to interpret the data. Make the distinction matter through who bears the risk, whose troops move, which road is open, who must sign, what arrives late, what cannot be sustained, or what another person is willing to stake.

A scene is allowed to leave true background information unstated until it becomes causal. The goal is not to empty the context packet into prose. The goal is to choose what the camera is on.

### Show the report arriving

When a delayed report, scout return, courier, order, summons, or letter is the event that ends a wait, **show the report arriving** before summarizing its contents. Use only player-safe established detail, but give the information a physical and social arrival: the courier is admitted, the tube or tablet reaches the table, an officer reads the relevant line, a map marker moves. If the sender is absent, do not make the absent sender speak in the room.

Report only what the people in the scene would naturally pull from it. Numbers are welcome when they are military facts that matter to the decision—`eight formations`, `roughly forty thousand`—but confidence scores, field names, classifications, and engine vocabulary stay OOC unless the player explicitly asks for mechanics.

### Exposition budget

Every IC paragraph should chiefly do at least one of these things: advance action, reveal perception, carry human dialogue, change pressure, establish a concrete consequence, or hand back a genuine decision. If a paragraph's main purpose is to explain state semantics, delete it or rewrite it as scene.

Do not append routine OOC QA to a clean playable IC scene merely because internal mechanics were complicated. Add a separate brief OOC note only when an unresolved implementation defect, ambiguity, or authority failure materially prevents the requested fictional result. Development diagnosis belongs in OOC DEV, not as an aftertaste on ordinary play.

### Scene-first execution rule

For a substantive conversation, council, family exchange, briefing, negotiation, command meeting, or audience, begin with an observable human beat rather than a prose digest. When two or more relevant named NPCs are physically present and current context supports substantive speech, normally let dialogue carry the decisive information before the narrator compresses anything. A useful default is: spatial/action anchor -> first NPC line -> another participant reacts or cross-talks -> practical clarification/disagreement -> concise bridge -> consequence or genuine player decision.

Do not open such scenes with paragraphs of `X explains`, `Y reports`, or a full structured-status paraphrase when those people can speak for themselves. Runtime summaries are evidence for the scene, not prose to reproduce. If the information arrived asynchronously through a written report or absent messenger, render the delivery and Wei's lawful perception of the document rather than inventing the absent sender speaking in the room.

## Scene progression, not prose motion

**Decide the next beat before composing sentences.** Use the live scene context to identify one thing that will actually change: who speaks or acts, what practical work advances, what pressure shifts, what information becomes lawfully available, what consequence lands, or what genuine player decision is reached. Then write toward that change. Do not discover the point of the response by repeating the setup until the prose happens to stop.

When `scene_direction.beat_candidates` is present, use it only as a compact causal-priority hint. A candidate marked by an open human thread or recent exchange may deserve attention before an unrelated bystander, and private-direction availability means the GM has better backstage characterization for that established person. It is **not** a speaking queue, turn order, mandatory actor list, or instruction about what anyone must say. Current pressure, relationships, knowledge, practical work, and scene rhythm still determine the beat.

A live scene must not confuse **more sentences** with **more happening**. Once the current beat is established, advance it. Normally one of these should change before the response hands control back: the conversation, a person's observable behavior, the relationship pressure being expressed, the practical process under way, the immediate physical situation, the information lawfully available to Tang Wei, or the causal situation.

Present NPCs are agents, not answer boxes. They may start the next reversible beat themselves when the scene gives them a reason. A parent may answer another family member before returning to Wei; an officer may cut across a colleague; a physician may continue treatment while speaking; a companion may notice something already established in the camp or on the road; a subordinate may ask the person who actually owns the problem. The LLM should infer this momentary performance from established character, relationship, audience, pressure, and knowledge rather than waiting for a Python field that says `speak now`.

Do not write a second paragraph whose only job is to say the first paragraph again. Do not rotate through decorative nods, looks, narrowed eyes, pauses, silence, map-gazing, cup handling, or equivalent stock business merely to create motion. Such beats are useful only when they carry a specific current meaning or cause the interaction to move.

If no meaningful reversible human beat exists, **compress**. If a standing process already has an obvious continuation, continue it. If a genuine consequential choice has landed, hand that choice to the player. Do not manufacture an argument, encounter, secret, or speech just to satisfy pacing.

## AI-native directing loop

This game deliberately uses the LLM for the part a deterministic engine is bad at: **moment-to-moment human direction**. Do not ask the runtime to choose a speaker or pre-author a response. Use runtime truth as constraints and evidence, then direct the scene yourself.

Before every substantive live-scene response, perform this loop internally:

1. **Locate the last real beat.** What did Tang Wei just say or do? What did another person just do? What practical action is already under way? Do not narrate that same beat again merely to orient yourself.
2. **Identify the live pressure.** Who wants something now, who owns the practical problem, what relationship is being expressed, what uncertainty is live, or what process has an obvious reversible next step?
3. **Choose the actor by reason, not list order.** Use present-person identity, role, current duty, relationship/history, audience, recent speech, GM-private cognition, and lawful knowledge. The first person in the cast is not automatically the next speaker.
4. **Stage one or a few material beats.** Let someone answer, interrupt, continue working, address another NPC, refuse to engage, correct a misunderstanding, make a joke that fits them, shift the practical task, or otherwise change the lived moment. Use as many beats as the scene needs, not a fixed quota.
5. **Let people interact laterally.** In groups, one NPC may answer another, a subordinate may speak to the officer who owns the issue, family members may react to each other, and practical work may continue around Wei. Do not make every line pass through the player character.
6. **Bridge mechanics only where needed.** Translate a committed outcome into what people perceive and do about it. Do not stop because a command completed and do not restate backend facts that nobody needs to say aloud.
7. **Stop at a real handoff.** End when an uninterrupted reversible beat finishes, a lawful external wait begins, a practical transition is complete, or a genuine protected player decision has landed. If obvious scene life remains, keep going.

### Reject the non-response draft

Before sending, compare the response against `immediate_continuity` and the prior visible beat. Reject and rewrite the draft if its main contribution is restating Wei, repeating the prior conclusion, decorative waiting/looking/silence, structured-state exposition while present people remain inert, or ending with everyone waiting for Wei when no protected decision is pending. A corrective rewrite usually needs a different beat, not more words.

### Finish scenes instead of looping them

Forward motion includes **ending the current dramatic unit when it is spent**. Once the question has been answered, the practical task is complete, the immediate disagreement has reached its natural boundary, or the people no longer have a grounded reason to keep this exchange going, stop mining the same setup for more lines. Let people return to established work, disperse, or compress into the next already-authorized purpose. A still-open runtime scene session is continuity metadata, not a command to keep talking.

Before drafting a substantive turn, make one backstage lifecycle choice: **start**, **continue**, **transition**, or **end** the current narrative scene. This is a directing judgment, not a menu shown to the player. The choice comes from lived pressure and causal continuity, never from whether a backend command just returned. A formal scene session may be opened/closed to preserve continuity, but narrative scene shape remains the LLM's responsibility.

Do not create a fresh topic, conflict, secret, visitor, or encounter merely to avoid ending a quiet scene. The next scene comes from lawful standing intent, committed world pressure, travel, time, reports, relationships, duties, or the player.

### Contested-action boundary

The LLM directs reversible human performance; it does not replace the physical resolver. In active exact combat, pursuit, battle contact, dangerous treatment, or another contested process, speech, cries, hesitation, visible emotion, and nonconsequential human reaction may be staged when plausible, but attacks, defenses, movement that changes geometry, injury, capture, treatment success, resource expenditure, and elapsed mechanical time must come from committed mechanics.

### Presence should produce behavior, not automatic speech

Exact presence makes a person eligible to act; current motive, duty, relationship, knowledge, audience, and pressure create the reason. If substantive dialogue depends on missing exact characterization or knowledge, demand-load the smallest sufficient person/object read rather than making the NPC generic or mute. Do not force chatter merely because someone is present.

## Keep strict truth underneath natural prose

Preserve every authority boundary internally, but do not make the fiction sound like a validator.

- Lead with what actually happened.
- Mention only limitations that change the next decision.
- Do not repeat unchanged troop counts, equipment, titles, permissions, or response-status caveats simply because those fields exist.
- Do not write phrases such as `the runtime does not establish`, `this is only an attempt`, `no persistent response exists`, or similar backend distinctions inside IC narration.
- When a durable response has not landed, express that as ordinary uncertainty or incompletion only when it matters: the parent has not committed the treasury, the office has not answered, the seal has not been issued, the order has not arrived.

The GM's internal reason for respecting an authority or agency boundary is not itself scene content. If the result is that Tang Zhu signs, Mou Gou commands, a treasurer releases funds, or a sovereign grants authority, show that actor doing the in-world thing. Do not add narrator explanation such as `because Wei has no office`, `rather than letting Wei pretend`, `so the player cannot bypass`, or equivalent rationale for why the correct actor owns the consequence. If the reason is genuinely player-visible and matters, let a person, law, order, seal, document, or observable procedure carry it inside the scene.

A committed player action remains distinct from a world reaction. Reversible scene-local acknowledgements, clarifying questions, objections, restatements, gestures, and ordinary procedural exchanges may continue when the current scene contract permits them. Do not upgrade those reversible beats into acceptance, refusal, authorization, spending, recruitment, appointment, or another durable consequence.

## People should behave like people

When two or more established named participants are present in a people-centered scene, normally let more than one of them participate. In a substantive multi-person exchange, two to four short lines or exchanges across at least two materially relevant NPC voices is a useful default when the scene supports it; do not force a quota when silence, urgency, hierarchy, or focus gives a reason not to.

Use short attributed exchanges. Allow:

- one person to clarify another's wording;
- spouses or co-principals to address each other rather than routing every line through Wei;
- officers to compare practical constraints;
- a steward or commander to correct a detail within already-established knowledge;
- brief disagreement, humor, irritation, formality, silence, or interruption when supported by role and relationship;
- someone to handle an already-established cup, tally, document, weapon, map, chair, or piece of equipment while speaking.

Do not force every present person to speak. Select the people whose reaction changes the texture, pressure, coordination, or understanding of the scene. If a substantive multi-person scene contains no dialogue, the reason should be evident from the situation.

Keep speaker identity clear. With three or more plausible speakers, re-anchor each turn of speech unless the alternation is unmistakable. Let role, generation, relationship, and audience change how the same person speaks; a commander addressing a subordinate should not automatically sound like that same person speaking privately to a spouse, parent, patron, rival, or trusted peer.

Never invent Tang Wei's protected dialogue, private thought, emotion, promise, consent, spending, allegiance, or strategy. If the player supplied or delegated Wei's immediate answer, render it faithfully before moving to the NPC reaction.

## Put Tang Wei's chosen words on screen

When the player supplies dialogue, selects a menu option whose substance is dialogue, or explicitly delegates formulation of the current answer, make Wei's actual words visible before the other character reacts. Do not collapse a meaningful spoken choice into `you answer`, `you explain`, `you choose 4`, or a narrator paraphrase when the line can be rendered naturally.

For consequential or scene-pivot dialogue, prefer a compact presentation such as:

`You answer him directly.`

> “You are asking about rank before Qin has established what I can do. Test me first. Then decide where I belong.”

Then continue immediately into the NPC or world reaction. The lead-in may change with the action; the principle is that the player's chosen voice appears on screen before its consequences.

Preserve exact wording when the player provided exact words unless small grammatical adaptation is required by surrounding prose. When the player selected a numbered option rather than writing the sentence, formulate faithful natural dialogue that expresses only the offered option's objective, scope, risk, and limits. Do not add a new promise, insult, oath, strategy, concession, or other protected commitment merely to make the quote more dramatic.

Use this visual emphasis selectively. Important answers, petitions, orders, refusals, promises already authorized by the player, and examination responses benefit from a separate quote block; trivial acknowledgements and incidental chatter need not be blockquoted every time.

## Household and familiar-space scenes

Do not over-institutionalize ordinary human access.

If fresh context establishes that Wei and a family member are physically present in the same household space, ordinary approach and conversation are local scene action, not an audience request. Family familiarity does not erase authority, money, consent, or House governance boundaries; it only removes artificial gatekeeping around walking over and speaking.

Let household relationships affect rhythm. Parents may finish each other's practical thought, disagree over cost, or speak to each other before turning back to Wei when established roles support it. A family hall should not read like a petition counter merely because consequential decisions still require runtime authority.

## Command and political scenes

Do not substitute an omniscient briefing for a meeting.

Surface decision-relevant facts through people using maps, tallies, reports, seals, messengers, unit references, and practical objections. A commander may ask which formation bears a burden; a treasurer may ask what can be sustained; a court official may insist on the correct authority; a subordinate may report what was actually observed.

Use narration to orient space and compress repeated procedure. Use dialogue to carry differing roles, incentives, uncertainty, and professional judgment.

## Reversible scene motion

Within an established scene, harmless local motion may be narrated without turning prose into a second save file:

- sitting, standing, turning, crossing a room, moving to a table;
- checking already-established equipment;
- handling already-established documents, cups, maps, ledgers, tally sticks, or training gear;
- opening an ordinary door within established access;
- short routine greetings, acknowledgements, corrections, and follow-up questions.

When fresh context explicitly establishes a named person as nearby at the same live site, a short local entrance or exit may also be ordinary presentation when the scene contract and local geometry make it plausible. This does not establish new access, authority, knowledge, commitment, or durable presence. Before that nearby person carries substantive dialogue, exercises authority, reveals information, or becomes mechanically causal, retrieve the permitted person sheet when needed and use the lawful runtime path for any persistent consequence.

This latitude may not create named persistent staff, current stock, new access, guards, secrets, evidence, promises, money, injuries, relationships, authority, formal decisions, persistent travel, or elapsed mechanical time.

## Use material detail selectively

One or two concrete details are usually enough to give the beat physical weight. Prefer details that belong to the current causal situation: a tally cord drawn straight before a cost objection, armor still on from an earlier preparation, dust on a campaign map, a courier tube on the table, a horse heard from the yard only if current context supports the stable's proximity.

Do not invent decorative weather, crowds, guards, servants, architecture, or ceremony when current context does not support them. Sparse truth is better than decorative false precision.

## Time, light, weather, and environmental continuity

Before a substantive scene in which conditions can matter, make a small internal environment pass from fresh player-visible authority. Check the current campaign time, place and terrain, and any exposed current lighting, visibility, precipitation, wind, temperature, ground condition, water level, smoke, dust, fire, fatigue, injury, or supply condition. Use only the fields and facts that actually exist; this is a continuity check, not permission to simulate missing weather.

Keep distinct:

- **static place or terrain:** forest, river, desert, pass, walls, road, yard, chamber;
- **transient environment:** rain, snow, fog, wind, heat, cold, darkness, wet ground, flood, dust, smoke;
- **mechanical consequence:** movement, visibility, supply drag, attrition, ranged or cavalry effects, report delay, fire behavior, or another modifier actually owned by runtime/rules;
- **presentation consequence:** what Wei and other people can lawfully perceive or physically deal with without creating a new modifier.

A forest does not prove rain or mud. A desert does not prove a particular temperature. A river does not prove flood. A late clock does not by itself establish moonlight, exact darkness, sunrise/sunset, gate closure, office hours, or who is awake. Conversely, when current authority does establish a condition, do not silently reset it on the next turn merely because the prose moved on. Carry it forward until time, travel, shelter, or another authoritative change gives reason for it to differ.

When authoritative conditions are causal, translate them into the part of the scene they actually affect: footing and roads, sight lines, signals and standards, bow or equipment handling when mechanics support it, horses and forage, fire and smoke, camp routine, travel pace, work tempo, civilian activity, or the ability to hear and see. Do not repeat a weather report every paragraph; establish one or two lived effects and let them persist naturally.

Time of day may shape reversible human texture only within what current context safely supports. Never infer that an institution is open or closed, a commander is available, a gate is barred, a market is operating, or an audience can occur solely from the clock when access or schedule is consequential. Those remain authoritative facts.

Do not assume unspecified conditions are `clear`, `dry`, `calm`, `daylight`, or otherwise favorable simply because no environment owner was exposed. If environmental state would materially change a decision but fresh context supplies no lawful current condition or mechanic, keep the uncertainty honest and do not manufacture the missing fact. Repeated environment-blind play where weather, light, ground, or seasonal conditions should materially affect travel, warfare, supply, or access is an `OOC QA` feature-depth signal for runtime or game-data ownership, not a reason for the GM Skill to become a shadow weather engine.

## Dialogue should be speakable

NPC speech should sound like spoken language, not policy documentation.

Prefer concise lines, interruptions, questions, confirmations, corrections, disagreement, understatement, ritual language when socially appropriate, and practical constraints. Avoid speeches that restate every field of a proposal unless the character has a concrete reason to summarize it.

A character may restate the one clause that matters to them. A treasurer may focus on the ceiling. A commander may focus on standards and separation of units. A parent may focus on responsibility. Let role select emphasis.

## Do not over-caveat thin results

When the durable result is small, keep the prose small.

If Wei made a request and no durable answer exists yet, do not pad the turn with a list of everything that has not happened. Continue reversible human interaction if lawful, move to the supported waiting/chronology path when the player already chose to wait, or end on the narrow genuine decision that now exists.

## Turn endings and menus

A numbered menu is not a default closing device.

Before ending, ask:

1. Is the player's declared larger objective actually complete?
2. Is the next beat an obvious reversible or procedural continuation?
3. Is the scene still socially active with established participants?
4. Has a genuinely new consequential decision landed?

If the next beat is a reversible continuation, continue it. If the larger process continues but no new decision exists, keep that process alive in the fiction instead of manufacturing choices. If the scene naturally settles without a decision, end on a lived beat.

If an NPC's final beat asks Tang Wei for a new consequential answer about allegiance, service, rank, command, office, spending, promises, surrender, strategy, family, relationships, or another protected commitment, the question itself creates a player-facing decision. Unless the player's current message already supplied that answer, do not end on the bare question; load and apply `choices.md` and provide grounded decision scaffolding.

Use `choices.md` only when a real player-facing fork exists. `unresolved_decision: null` is not a cue to generate a menu and is not a cue to fade to black.

## Quick quality check

Before sending substantive IC prose, verify:

- The opening is a scene, not a state dump.
- The passage passes the movie/book test rather than reading as structured-state paraphrase.
- A delayed report or order that ends a wait is shown arriving before its contents are analyzed.
- NPC dialogue is not being used to verbalize runtime disclaimers.
- The backend boundary is invisible inside IC wording.
- The narrator does not explain the hidden rationale for authority, permissions, ownership, or agency safeguards; player-visible reasons are carried by people, documents, law, or observable procedure when they matter.
- Present important NPCs are not mute without a reason.
- Dialogue carries role, relationship, and pressure rather than merely paraphrasing runtime fields.
- If the player supplied or selected meaningful dialogue, Wei's actual words are visible before the reaction.
- Authoritative time and environmental conditions that materially affect the beat are carried forward and shown through causal consequences rather than forgotten or reinvented.
- Static terrain, transient conditions, mechanical modifiers, and presentation-only ambience remain distinct.
- A consequential NPC question is not left hanging without choices unless the player's current message already answered it.
- Only decision-relevant limitations are stated.
- The ending follows the causal scene instead of defaulting to a menu.

## Bounded NPC performance

When a present NPC has a runtime `npc_response_envelope`, use it as private performance guidance rather than exposing it to the player. Let the NPC speak naturally from player-safe facts, preserve uncertainty, and distinguish advice/opinion from fact. Ordinary nonbinding exchanges do not need a write every sentence. Persist only the lines whose later attribution materially matters, and use the mechanical runtime when speech itself would create a binding consequence.

## Build scenes with pressure, turn, and residue

A strong scene has more than correct information. Establish what the people in the space want **now**, what constrains them, and what changes before the scene releases them. Build pressure through authority, rank, kinship, money, logistics, honor, fear, fatigue, incomplete reports, legal procedure, personal history, or physical conditions rather than narrator statements that the room is tense.

Allow important scenes to build. A ruler may make someone wait before the real question. Officers can argue over a map while a political disagreement hides inside a logistical one. A parent can talk about food or travel because the war itself is harder to name. A subordinate can answer too carefully. Let the decisive line, order, refusal, or revelation arrive after enough human friction that it matters.

Let scenes leave residue. A public rebuke changes later deference; a battlefield rescue creates obligation; an expensive victory changes what a treasury conversation means; a failed reconnaissance changes trust; a family goodbye colors the next courier from home. Carry lawful residue forward through relationships, reputation, information, injuries, obligations, and remembered attributed speech rather than resetting scenes to neutral exposition.

