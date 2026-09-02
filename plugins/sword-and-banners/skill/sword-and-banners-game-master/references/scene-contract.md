# Scene Contract

This reference defines the boundary between hard simulation truth and fluid human roleplay. The two RPGs may mirror this contract independently, but each repository remains self-contained.

## Three layers of truth

1. **Hard world truth** is runtime-owned. Movement over meaningful distance, elapsed campaign time, injury, death, combat outcomes, money, resources, equipment ownership, training gain, office, formal orders, contracts, promises with mechanical consequences, relationship changes, secrets, custody, formation movement, territory, diplomacy, and other irreversible consequences require runtime authority.
2. **Bounded scene truth** is GM-owned inside fresh runtime limits. Present NPCs may acknowledge, clarify, advise, object, disagree, speculate from lawful evidence, ask follow-up questions, joke, interrupt, discuss established facts, and express nonbinding opinions without a bespoke mechanic for every sentence.
3. **Connective presentation** is freely reversible. Posture, pauses, looking at a map, sitting, standing, handling already-established objects, tone, silence, and a few plausible steps inside the established space do not require a write.

Be permissive about reversible fiction and strict about persistent consequence.

## Active scene sessions

Treat an active scene session as presentation and continuity state, not a second mechanics engine. Sword scene presence must still agree with exact current person owners and Tang Wei's exact location. It may identify the exact established participants, location, process, purpose, agenda, open conversational threads, and a soft scheduling boundary. It never moves bodies, creates access, grants authority, spends resources, changes relationships, or proves hidden facts.

A planned meeting duration is a soft boundary. Do not dismiss participants merely because the nominal duration has elapsed while Wei is still lawfully present and the scene remains active. The session ends because it is completed, Wei leaves, a hard interruption occurs, the player explicitly skips to the conclusion, or another lawful scene supersedes it.

When the player begins a substantive response-bearing interaction with an established, exactly co-located NPC and no active session exists, the interaction path may automatically establish a lightweight `conversation` session within that same semantic action whenever thread tracking or multi-exchange continuity will matter. Explicit scene opening remains available for a council, audience, briefing, or other scene that exists before Wei makes the first conversational move. Never require the player to spend a separate turn requesting session bookkeeping or expose the session mechanic IC. Do not create a session merely for a greeting, a trivial acknowledgement, or a one-line exchange that needs no durable thread.

## LLM-owned scene lifecycle

Formal session state exists to preserve continuity, not to decide story structure. The LLM may begin a narrative scene from any fresh lawful situation without first opening a formal session. When a substantive co-located people scene will benefit from persistent participants, threads, attributed speech, or reversible scene facts, the LLM may open the presentation-only session itself through `gm_scene_context.scene_direction.scene_lifecycle` and the exact `scene_session_action` contract. Never ask the player to manage this bookkeeping.

Likewise, the LLM decides when the lived scene is complete. A runtime transaction ending is not a scene ending. Close the formal session when its actual human/practical purpose is spent, the player leaves, a hard interruption supersedes it, or the player skips/cancels it. Do not casually close across a still-material open human thread or protected Tang Wei decision because closing may abandon presentation continuity. Narrative transitions that require travel, elapsed time, combat, access, appointment, resource transfer, or another durable change still require their real authority before prose crosses that boundary.

## Active-session motion and participant agency

A live session is **continuity, not a turn lock**. Its participants do not freeze after Tang Wei speaks, after one runtime write settles, or while an open player question remains. Every fresh read must revalidate session participants against exact current person locations and Tang Wei's exact location; a participant who has lawfully left, entered custody, become unavailable through exact combat/movement, or otherwise ceased to be co-present must not be kept in the scene merely because an old session row names them. Conversely, an exactly present participant who remains in the active session is still eligible for reversible speech and action even if no new Python response object was created.

On bare `continue`, or after Tang Wei has already acted, the LLM may take the next grounded beat through any established present participant: a reply, interruption, cross-talk, practical work, a changed posture that matters, withdrawal from the exchange, a question to someone other than Tang Wei, or a meaningful silence. The session is never an instruction to wait for Tang Wei to activate each person. If one participant lawfully departs, prune that person's scene eligibility without erasing the remaining people or the unfinished human/practical thread.

If a formal session survives in continuity state but fresh physical projection shows that its other participant(s) are gone, treat that as a **lifecycle reconciliation signal**, not as permission to keep them speaking offscreen. Do not resurrect opaque open-thread refs as live dialogue merely because the durable session remembers them. If materially relevant people remain, continue with those who are actually present; if no other participant remains, close or transition the formal session at the next lawful narrative boundary unless a hard process is about to supersede it anyway. The absent person's unanswered thread may remain durable for later resumption if they lawfully meet again.

This latitude is still presentation-only. It cannot create elapsed time, movement between meaningful locations, access, acceptance/refusal, injury, command, resources, relationship mutation, information the speaker does not lawfully possess, or another hard consequence. Those remain owned by their actual mechanics.

## Pre-conversation scene direction

A scene session preserves continuity; it does not switch NPC intelligence on. When fresh context exposes `scene.gm_private_director_context.present_people_context`, use that bounded backstage packet for exact established present people even before Wei addresses them. It may ground spontaneous reactions, interruptions, questions, jokes, cross-talk, silence, or ordinary departure. Do not manufacture activity merely because someone is listed, and do not expose private truth as Wei knowledge.

## LLM scene progression duty

An active scene session preserves continuity, but the LLM must still **direct the next human beat**. Do not wait for a new runtime response envelope merely because the last mechanical write is settled. If established people are present and no protected Tang Wei decision or hard causal interruption blocks the moment, use current role, relationship, audience, recent speech, open threads, practical work, and GM-private direction to decide whether someone speaks, reacts, interrupts, continues a task, addresses another person, withdraws, or lets a meaningful silence stand.

A repeated paraphrase of the same premise, the same conclusion in new wording, or stock physical filler such as nodding, staring, narrowing eyes, or pausing without changing the interaction does not count as continuation. If there is no fresh beat worth showing, compress or transition. Do not turn this into a dialogue quota and do not invent hard truth merely to keep the scene moving.

## NPC response envelopes

When `get_person_sheet` or fresh context exposes an `npc_response_envelope`, use it as GM-private performance guidance. It defines what the NPC may safely do in ordinary dialogue and what kinds of consequences ordinary speech cannot establish.

Generate player-facing dialogue from what the speaker actually knows and chooses to disclose. When the runtime explicitly supplies `gm_private_cognition`, the GM may use hidden goals, duties, memories, beliefs, knowledge, or motives to decide **which response the NPC chooses**, including truthful disclosure, concealment, lying, bargaining, refusal, hesitation, or initiative. That private block does not become Wei's knowledge and must never simply be quoted as hidden thought or omniscient exposition. If the NPC says or visibly does something because of it, persist only the observable statement/action. The envelope never authorizes a hard consequence by itself.

Ordinary reversible dialogue does not need a runtime write every sentence. Persist an important line only when durable conversational continuity materially benefits later play. Persisted scene speech is an **attributed statement**, not objective world truth.

The AI is not a renderer for structured fields. Runtime records establish what is true, what is known, what is privately relevant to the NPC when explicitly supplied, and which consequences remain unavailable; they do not prescribe sentence structure. Within those boundaries the GM may invent **ephemeral subjective performance** such as a clipped answer, a pause, irritation, amusement, embarrassment, warmth, impatience, uncertainty, a change of tone, or a nonbinding opinion that makes human sense in the moment. Such characterization is reversible scene truth. It must not be used to assert a hidden factual motive, secret loyalty, undisclosed event, guaranteed future behavior, relationship mutation, or another durable fact that the runtime has not established.

## Interaction depth and differentiation

Treat substantive interaction as a sequence of **meaningful conversational moves**, not as prose wrapped around a state summary and not as turns allocated across the attendee list. This rule applies across councils, family scenes, command meetings, audiences, negotiations, briefings, interviews, camp conversations, institutional exchanges, and other multi-turn social scenes.

Before giving a materially relevant present NPC substantive dialogue, retrieve that person's permitted sheet when the compact cast does not already supply enough role/voice context. In a crowded scene, retrieve only the people whose contribution matters to the current beat rather than loading the whole room.

Use `npc_response_envelope.performance_cues` as follows:
- `public_role_context` and `role_lens` identify the lawful public or social perspective from which the person can naturally question or emphasize established facts;
- `professional_lenses` identify player-visible areas of demonstrated service competence that may shape what the person notices, tests, clarifies, or advises about;
- explicit safe speech/temperament cues, when present, may shape delivery but never create knowledge, motive, authority, or outcome;
- absence of personality cues is **not** a reason to make everyone sound alike. Differentiate speakers first through rank, generation, education, role, demonstrated behavior, relationship, audience, vocabulary, directness, and formality when those are player-safe and established.

Expertise is a **performance lens, not a speaking quota**. A strategist does not owe the scene a strategy paragraph merely because strategy is being discussed, and a logistician does not have to speak whenever supply appears. Use expertise to shape what a person naturally notices when that person has a reason to enter the exchange.

When a speaker naturally has the floor, let the line do real conversational work when appropriate: question an assumption, identify a practical constraint, object to a consequence, compare alternatives, ask who bears a burden, clarify authority, recommend a reversible next step, or expose an unresolved tradeoff. Do not manufacture a line merely to satisfy one of those categories.

### Shared premises and motivated questions

Before writing a substantive question, separate **shared premises** from **live unknowns**. A fact that fresh context already establishes for everyone in the exchange, or that is logically entailed by the immediate chronology and position, normally belongs in common ground rather than in a question-and-answer sequence.

Every substantive NPC question should have a conversational motive. It should obtain genuinely missing information, test a disputed assumption, force prioritization, expose a tradeoff, clarify responsibility or authority, challenge a proposal, or determine what should happen next. Do not use dialogue to audit runtime fields or translate a structured briefing into an interrogatory checklist.

Do not make people solemnly reconfirm the obvious merely because a status field exists. For example, if Qin is still staged at Kanyou awaiting authority to enter Wei and no separate scout, border, or contact event establishes otherwise, do not make a commander ask whether battle contact is confirmed just because an intelligence record contains `contact_status`. The shared premise is that the field armies have not yet met the enemy. A useful military question would instead pursue a live unknown: which reports are reliable enough to shape the first march, which enemy movements are actually observed, or what reconnaissance can narrow the estimate before entry, when those questions are supported by player-safe evidence.

Confirmation is natural when the fact is surprising, disputed, newly changed, legally consequential, or the speaker needs another person to commit to the wording. Otherwise let established facts remain implicit. Characters do not need to recite obvious premises to prove that they understand them.

### Decision-bearing command speech

In a war council, command conference, briefing, or headquarters scene, a commander who has the floor should use it to communicate the **positive military structure, assignment, constraint, or decision** that matters. If fresh context already exposes concrete objectives, command assignments, reserve responsibilities, route facts, or an adopted/proposed hierarchy, put those facts on screen instead of spending dialogue on generic military maxims.

Do not use **straw-alternative exposition** as filler. Lines such as `we will not march one hundred seventy-six thousand men as one enormous army` or `we will not scatter every general onto his own campaign` are useless unless someone actually proposed those alternatives, they are genuinely disputed, or rejecting one of them changes the decision. When nobody proposed them, skip the negations and state the actual arrangement: who is under whose command, which subordinate commands form the main body, which are detached to a separate axis, which are reserve, and what objective or constraint justifies that structure.

Preserve the command hierarchy exactly. An intact subordinate army or command group can retain its own commander and internal organization while still being operationally subordinate to the campaign's supreme commander. **Internal command integrity is not strategic independence.** When `march_planning.campaign_scheme.command_hierarchy` is available, treat its `supreme_campaign_field_army` structure as the positive campaign model: listed state-owned commands are nested beneath supreme campaign command; a distinct objective/axis or reserve role is what marks an operational detachment. Do not describe every named general as running a separate campaign merely because their persistent command group remains intact.

When the live projection distinguishes a Qin-owned subtotal from a larger recursive command span, use the **full recursive command span** for the army's physical size and movement burden while preserving the ownership split. Do not single Tang Wei out as the only commander with private troops when other exact field-command hierarchies also contain House or retinue subcommands. State-owned, House-owned, and other non-state bodies remain separately owned even when they march inside one intact field army.

A staff plan and a binding order remain distinct. If the runtime exposes only a staff scheme, present it as the concrete scheme being proposed or discussed rather than silently promoting it to an issued order. But lack of a binding order is not a reason to replace available specifics with vague prose. State the plan's real objectives, subordinate commands, strengths, axes, reserve, and route/supply constraints that the player can lawfully know; then surface only the actual unresolved decision.

Do not append **authority boilerplate** after a concrete military answer. If entry authority, a withheld seal, or another legal boundary is already shared context, mention it again only when it changes the immediate requested action. Avoid endings such as `the disposition is mine to settle, but crossing is not` when the player asked who is assigned where. End on the actual assignment, unresolved command question, or observable next staff action instead of restating a standing permission boundary.

### Dialogue choreography

**Information follows the interaction.** A player-safe fact does not require an NPC mouth. Neutral established facts, exact figures, and concise context may be compressed by narration when forcing them into speech would sound artificial. Keep exact mechanically important figures exact when they matter, but do not make several NPCs repeatedly verbalize them just to demonstrate fidelity.

The attendee list is **not a speaking queue**. Do not write round-robin dialogue in which each present named person is handed one line. Uneven participation is expected. One person may dominate several exchanges; another may answer once; another may interrupt; another may remain silent throughout the beat. The same speaker may stay active across follow-up questions when that is how the interaction naturally develops.

Avoid the **analytic chorus**: one speaker states a fact, another supplies the caveat, a third supplies the implication, and the narrator then explains why the exchange mattered. Also avoid `fact -> caveat -> implication -> narrator significance` as a default scene rhythm. A second speaker should enter because they actually change the interaction through disagreement, consequence, burden, alternative, authority, humor, confusion, refusal, or a genuinely new question—not because the prose needs another voice.

People should respond to the **meaning** of what was said, not merely restate the same datum in different words. If someone says the enemy estimate is broad, the next natural response might challenge the plan that depends on the estimate, ask what reconnaissance can narrow it, dismiss it as insufficient for a decision, or move on. It should not normally be another reformulation of `the estimate is uncertain`.

Allow spoken language to remain spoken. Short answers, fragments, hesitation, interruption, silence, correction, deference, refusal, dry humor, unfinished thoughts, and a speaker changing course mid-sentence are valid when consistent with established competence, rank, relationship, and pressure. Do not turn every contribution into a complete explanatory paragraph.

Do not manufacture a question or objection solely to give a speaker a conversational job. If a person's role adds nothing useful to the current beat, let that person remain silent, react nonverbally, or wait for a later point where their perspective matters.

When the player-safe facts are thin, use **uncertainty as playable material** instead of inventing detail. A strategist can ask which evidence supports an estimate; a logistician can ask what burden a route must carry; a legal official can question what authority a seal actually grants; a family member can ask what a decision means for the household. The question or opinion may be generated from the safe lens, but any factual answer that would establish new world truth still requires lawful evidence or runtime authority.

Across a sustained multi-person scene, let materially relevant people participate when the interaction gives them a reason. Do not require multiple speakers in every beat. Runtime summaries are briefing material for the GM, never dialogue scripts.

### Speaker attribution in crowded scenes

When three or more people in the scene could plausibly speak, **every speaker change must be locally unmistakable**. Anchor the new speaker by exact name, established title, or an unambiguous action beat in the same paragraph as that person's first spoken line. Do not make the reader carry an attribution across several paragraphs or infer it from the attendee list.

Do not rely on alternating quotation marks, a bare `he said` / `she said`, or a pronoun inherited from the prior paragraph when another same-pronoun person is present. Pronouns may continue after a named speaker is established in the same local beat and no competing referent has intervened. After an interruption, narration break, subject change, third-party interjection, or a run of more than one other speaker, name the returning speaker again.

In a crowded command, court, family, or negotiation scene, avoid unattached quotation blocks. If a line could be reassigned to another present person without changing the grammar, the attribution is too weak. Before sending the scene, perform a **speaker audit**: a reader scanning the dialogue should be able to identify who says every line without reverse-engineering turn order.

### Do not narrate the narration

Do not explain that your own dialogue worked. Avoid narrator lines such as `that answer matters more`, `the distinction settles`, `the room understands the point`, `the discussion reaches a natural stopping point`, or `for the first time the argument becomes clear` unless a concrete observable reaction genuinely establishes that fact and the wording is still needed.

Do not narrate **authorial negative contrast**: never describe the bad, redundant, artificial, or over-explanatory version of the scene that the GM chose not to write. Lines such as `Mou Gou does not ask Shou Hei Kun to read the roster back`, `he does not need to explain the structure`, `there is no need to repeat the figures`, `rather than reciting the briefing`, or `instead of making everyone speak` are self-conscious commentary when the omitted action was never a live in-world possibility. Delete the contrast and show only what actually happens.

Negative wording remains valid when the absence itself is an observable in-world event that matters: a person refuses to answer, a messenger does not arrive by an established deadline, a commander withholds an order, or someone pointedly remains silent after being addressed. The test is whether Wei can perceive the absence as part of the world, not whether the narrator is explaining an avoided prose choice.

Let significance appear through what people do next: someone changes the proposed plan, stops arguing, asks a sharper question, writes an order, redirects the room, falls silent, or moves to another matter. Do not add a narrator paragraph interpreting a conversation that already demonstrated its own meaning.

Meeting transitions should also be enacted rather than announced. A council moves on because the chair redirects the room, a participant introduces the next matter, a document or messenger changes the subject, a decision closes the issue, or another observable event interrupts. Do not end a topic merely because the narrator declares that the matter is settled.

## Derived literary continuity

Fresh context may expose `literary_continuity`, a bounded hot index keyed by relevant people and place. These records are **interpretive literary memory**, not campaign authority. Use them to preserve earned voice, recurring references, relationship expression demonstrated on screen, unfinished conversational history, and established soft place texture across long gaps and fresh chats. They never prove hidden motive, permanent personality, relationship score, location, injury, ownership, access, resources, or command authority.

Persist a new literary-continuity note only when the memory is likely to improve later scenes. It must cite `basis_refs` to existing authority-false records in the active session, including at least one primary attributed-speech or reversible-scene-fact record; a continuity note may not bootstrap itself from prior interpretive notes alone. Prefer a few durable evidence-rich notes to constant summarization. Do not promote a newly improvised flourish into long-term memory unless it has lawful scene evidence to cite.

## Speech versus mechanical speech acts

Examples that may remain bounded scene truth when supported by player-safe context:
- professional advice;
- disagreement or objection;
- clarification of an already-established order;
- speculation explicitly framed as uncertainty;
- a personal opinion;
- a follow-up question;
- ordinary NPC-to-NPC cross-talk.

Examples that cross into hard world truth and require the relevant runtime mechanic:
- issuing a new binding order;
- revealing new secret factual information that no lawful runtime or GM-private authority already establishes;
- granting or revoking authority, office, access, rank, custody, money, equipment, or troops;
- accepting or refusing a contract, oath, alliance, surrender, marriage, or other mechanically consequential commitment;
- inventing a new objective secret fact, mechanically verifying a disputed claim, or promoting speech into authoritative knowledge without its real information authority;
- causing movement, injury, combat, recruitment, relationship change, or another persistent consequence.

An already-established private fact is different from a newly created fact. When fresh GM-private cognition establishes that the speaker actually knows it, the NPC may truthfully disclose it, conceal it, partially reveal it, distort it, or lie according to their goals and situation. The observable speech can become Wei-observed information through the normal scene/information path, but the speech record proves only attribution unless another authority verifies the underlying claim.

## Question lifecycle

A response-bearing player move inside an active session creates an open conversational thread only when the runtime records it as such. `ask` is one subtype; requests, petitions, offers, proposals, and other response-bearing moves use the same lifecycle. When an important answer is persisted for continuity, resolve that exact thread in the same write using its exact `resolves_thread_ref`; do not narrate a durable answer while leaving the mechanical thread falsely open. Closing a scene abandons its remaining unresolved threads rather than leaving them falsely active for weeks.

Do not treat a historical recent question as active merely because it was asked recently.

## Continuation and time

Bare `continue` resumes the active scene or already-declared process at the exact current campaign timestamp. It does not authorize a broad time skip.

If substantive conversation has clearly consumed material campaign time, commit conservative in-scene elapsed time only through the runtime's explicit active-scene time policy. There is no artificial maximum scene duration. A true hard causal interruption may end the reversible scene.

Finishing the meeting, leaving it, preserving it while some time passes, and explicitly skipping to its conclusion are distinct intents. Never infer one from bare `continue`.

## Durable scene history

Durable attributed speech exists to make fresh-chat continuity possible without turning conversation into a second rules engine. Preserve speaker, listener/session context, attribution kind, time, and player-safe basis when supported by the runtime. Historical speech can establish that **the speaker said something**, not that the statement was factually correct.

Keep live context bounded. Recent speech may be projected in the hot handoff while older attributed history remains available through exact history reads/shards.

## Decision UX

Do not append a menu after every paragraph. Continue reversible scene flow until a genuine unresolved Wei decision, material tradeoff, protected commitment, or hard causal boundary arrives. At that point, narrate the decision-relevant facts first and scaffold choices only when useful.
### GM-private direction versus Wei-visible knowledge

The GM is not required to be epistemically identical to Tang Wei. A good AI director often needs the real current-scene truth in order to make other people act consistently. Explicitly marked `gm_private` data may therefore contain information Wei has not discovered. Use it to make the world **behave correctly**, then filter the rendered scene through Wei's perception and lawful information. Do not leak private truth through narrator exposition, conveniently omniscient choices, or unsupported inference.
