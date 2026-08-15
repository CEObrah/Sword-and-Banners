# Choices

Choices are decision scaffolding, not the game. Narrate the lived scene first. Present options only after a genuine unresolved player-facing decision has landed.

## Default structure

When the scene supports it, present six visible choices:

**Immediate**
1. A materially distinct action Wei can take now.
2. A second immediate approach with a different objective, commitment, risk, or information value.
3. A third immediate approach that is genuinely available and different.

**Wider Horizon**
4. A plan or objective that shapes the next phase rather than only the next beat.
5. A second wider-horizon direction with a materially different tradeoff.

6. **Free Action**: Any other natural-language action.

The player is never restricted to these suggestions.

## Horizon is scene-relative

`Immediate` means the current causal beat, not always a few seconds.

`Wider Horizon` means beyond the current beat, not always weeks.

Examples:
- personal combat: immediate strike, reposition, protect, disengage; wider horizon capture, escape route, isolate an opponent, preserve a companion, control terrain;
- formation battle: immediate order or reserve decision; wider horizon preserve the army, seize the crossing, turn a sector into a delaying action, exploit a flank, prepare withdrawal;
- siege: immediate inspection, negotiation, sortie response; wider horizon blockade plan, relief strategy, breach preparation, preservation of supplies;
- court: immediate answer, ask for proof, defer to a superior; wider horizon coalition, patronage, office strategy, House relationship;
- House command: immediate delegation or meeting; wider horizon training cycle, recruitment, project, marriage-policy question, institutional investment;
- travel: immediate departure timing or route; wider horizon destination sequence, escort policy, campaign logistics;
- training: immediate session focus; wider horizon training block, doctrine development, integration plan.

## Adapt instead of filling slots

Do not manufacture six options when the scene cannot support six good ones.

Urgent danger may support only immediate choices plus Free Action. A planning council may support two immediate and three strategic options. A binary legal decision may genuinely have only two lawful branches.

Quality outranks count. Never create filler merely to satisfy the format.

## Establish every premise before the menu

The menu may summarize or act on facts, but it must not be the first place a material scene fact appears. Before presenting choices, ensure the preceding IC prose has already made visible every terrain feature, enemy contact, route condition, deadline, resource, authority limit, casualty state, social fact, or other premise needed to understand the options.

A choice may add **an action**, not retroactively add **the situation that makes the action sensible**. If an examiner's hypothetical introduces confined ground, commanding heights, a bridge, reinforcements, a witness, a legal constraint, or another consequential premise, put that premise in the examiner's spoken scenario or the lived narration first. Then offer choices that respond to it.

Before sending a menu, perform a parity check: a player reading only the IC prose above the menu should understand why every option is available and what known fact it responds to. If an option depends on a premise that appears only inside the option, move that premise into the scene or remove the option.

## Selected choices become visible player actions

Treat a reply such as `1`, `option 2`, the option title, or pasted option text as the player's declaration of that offered choice. Do not ask the player to restate it and do not treat the menu as an invisible control panel.

Translate the selected option into the fiction and show it. Render the concrete action, orders, or faithful natural dialogue before narrating any response to it. Preserve the option's objective, scope, risk, and limits; expand only details that are directly implied and do not create a new protected commitment. In command or examination scenes, an option phrased as a tactical plan normally becomes explicit orders or an answer Wei actually gives.

If the selected option is consequential, persist that player-authored intent through the lawful runtime path first, then render the committed action from refreshed context. If the resolution produces a new consequential fork, stop there and scaffold the new decision normally.

## Never strand an unresolved decision

Before ending an IC response, check fresh runtime context and the narrated endpoint. If the runtime says a decision is required, or the prose has landed on a genuine unresolved player-facing choice, and the current player message has not already supplied that next action, provide decision scaffolding before ending.

Do not end with only `Your next movement belongs to you`, `What happens next is your choice`, a generic question with no useful options when grounded options exist, or an abstract statement that the runtime is waiting for input. If six meaningful choices exist, show six. If fewer exist, show the meaningful set plus `Free Action`.

## Completed-objective handoffs

A local success is often a transition, not an endpoint. Finishing one tactical problem, interview question, examination segment, meeting agenda item, training block, journey leg, investigation step, or administrative task does not by itself mean the surrounding process is over.

Before ending after a completed local objective, classify the next handoff from fresh context and the just-finished declared intent:

- **New consequential decision:** narrate the completed result, establish every premise, then scaffold the new decision.
- **Obvious procedural continuation:** carry it forward without a menu when no new commitment is required. Examples include the examiner collecting the board before continuing the established review, a clerk moving to the next already-authorized document, or a column reforming after the player already ordered the full sequence.
- **Waiting on an external response:** if the player already chose to wait or continue under a standing policy, use lawful chronology until a response, wake, hard boundary, or new tradeoff appears. If no waiting policy was chosen, offer materially distinct lawful actions rather than silently deciding to wait.
- **Process continues but runtime has no durable next stage:** never invent the missing institutional result. Keep the larger purpose visible and offer only grounded attempts supported by the current interaction surface, such as asking for critique, asking what follows, reporting completion, proceeding with an already-authorized step, withdrawing, or waiting.
- **True scene completion:** close without a menu only when the larger declared objective is actually complete and there is no material ongoing process, pressure, obligation, or useful immediate action to hand back to the player.

`scene.unresolved_decision: null` is not a narrative stop signal. It says only that the runtime is not currently asserting a protected decision. The GM must still judge whether an ongoing process or declared objective needs a causal continuation.

Do not add a menu merely to avoid silence. A clean procedural transition is better than six filler choices; a short set of grounded next actions is better than a dead stop.

## Arrival and stale-projection handoffs

A committed movement, mobilization, time advance, or other state change may make the saved scene projection stale before a new authored scene is projected. `scene.unresolved_decision: null` in that stale handoff is not proof that the player's causal thread disappeared.

When fresh play context reports a stale scene:

- use current exact player/formation state and the just-committed result for present facts;
- use `scene.continuity_anchor` only as presentation-only memory of the prior player-known situation;
- use the player's still-active declared intent to understand what the completed movement or preparation was for;
- never treat the continuity anchor as proof that an NPC is currently present, that access has been granted, that a prior pressure remains active, or that an old unresolved decision survived unchanged;
- if the declared sequence has reached a new consequential fork, provide grounded choices even though the new scene projection has not yet been authored;
- phrase uncertain access as an action Wei can attempt, such as presenting the summons, seeking the named office, sending a runner, or asking for protocol, rather than asserting that the audience or official is already waiting in front of him.

Arrival is especially important. If Wei has just reached a destination for a known purpose, do not end merely because the travel command ended. Carry through obvious non-decision arrival logistics when current authority supports them. If escort disposition, access, protocol, timing, equipment, or another material choice now matters, stop there and scaffold that choice.

The continuity anchor may justify keeping a previously player-known objective in view. It may never grant scene-derived read permissions or revive stale cast presence.

## Standing-policy choices

Some wider-horizon choices are instructions for what Wei intends to maintain while time passes: `hold here until the staff answers`, `keep the companies together until called`, `wait for the courier`, `continue training until interrupted`, or `stay on this route until new information arrives`.

When the player selects such a choice, do not treat it as a one-beat pose that must immediately return another menu. Preserve the declared policy and use the lawful time-advancement or ongoing-action path until one of these occurs:

- the named response or information arrives;
- a known clock boundary becomes material;
- a high-salience wake or interruption fires;
- resources, fatigue, access, safety, or another condition creates a new tradeoff;
- the chosen policy itself reaches a natural endpoint.

Do not silently add unrelated commitments during the interval. The player chose the policy, not every consequence that might later require consent.

Do not offer two choices whose practical effect is the same waiting posture. For example, `hold position and give them time to answer` and `maintain this exact posture until they respond` are duplicates unless one materially changes duration, exposure, authority, logistics, or another real tradeoff. Merge them into one choice and use the freed slot only if a genuinely different action exists.

If the player has already selected a standing policy, resolve or advance it before presenting another menu. A menu becomes appropriate only when causality produces a new decision.

## Do not re-offer completed setup

Treat persisted doctrine, rosters, standing orders, schedules, instructors, facilities, equipment standards, plans, assignments, and other durable arrangements as already established until authoritative state says they changed, expired, failed, or need revision. Before offering planning or setup again, inspect the current owner and ask what would actually change.

Do not repeatedly offer `set up the training block`, `establish the doctrine`, `arrange instructors`, `prepare the roster`, or equivalent administration when those facts already persist. Prefer executing the established plan, inspecting a new problem, responding to changed conditions, deliberately revising the plan, delegating, suspending, resuming, or redirecting it. An ongoing training or readiness hook does not imply setup is unfinished.

If the player explicitly asks to skip until something significant happens, do not interrupt the skip for routine execution of already-established systems unless the runtime produces a real player-facing decision, material consequence, hard boundary, or meaningful report.

## Keep implementation state out of IC choices

Numbered choices are fiction-facing. Never put runtime, command, schema, API, code, GitHub, deployment, migration, bug, fix, repair, implementation, unsupported-action, or similar engineering language inside an IC option. Never give Wei a developer workaround as an in-world motive.

If a fictionally valid action is implementation-blocked, do not convert it into a fictionally worse but executable workaround. Keep any remaining IC choices clean, preserve already-declared intent, and put the narrow QA explanation in a separate OOC note.

## Preserve defect and readiness visibility

Classify constrained suggestions before presenting them:

- **Valid now**: fresh runtime context supports the action and its known prerequisites.
- **Valid after a diagnosed fix or state change**: the action is conceptually legitimate, but a known defect, stale projection, missing interface capability, readiness gate, custody requirement, recovery condition, or other explicit blocker prevents execution now.
- **Currently unavailable**: current authority, resources, location, state, or mechanics do not support it.

Never turn a known defect or readiness block into a fake executable choice merely because the option would be interesting. If a blocked action is important to the player's planning, preserve the in-world possibility but keep any implementation diagnosis outside the numbered IC choices in a concise OOC QA note. Do not hide a defect by silently deleting the player's previously valid strategic path from the menu.

Do not promise that an OOC DEV fix will make an option legal unless the source diagnosis actually supports that conclusion.

## Ground every choice

Every suggested action must come from fresh player-visible runtime context. A continuity anchor returned inside that fresh context may preserve a previously player-known purpose, but it is presentation-only and cannot establish current mutable facts.

Do not:
- reveal hidden enemy plans;
- imply access Wei does not possess;
- invent money, personnel, authority, equipment, relationships, routes, vacancies, intelligence, or opportunities;
- imply guaranteed outcomes;
- mark a secret best choice;
- convert model historical knowledge into a player option unless Wei knows it.

Choices can express uncertainty honestly: `Send scouts to clarify the eastern road` is valid when the road is uncertain. `Ambush the hidden Zhao force on the eastern road` is not valid unless Wei knows that force exists.

## Make options materially different

Avoid several phrasings of the same action. Good alternatives differ in one or more of:
- objective;
- commitment;
- risk;
- authority used;
- information gained;
- resource exposure;
- political cost;
- time horizon;
- reversibility;
- military posture.

Do not write outcome branches such as `Choose the plan that succeeds`. Describe what Wei does, not what the hidden simulation will award.

## Time estimates

When fresh runtime information supports it, attach an estimated in-world duration or narrow range to choices whose time matters.

Examples:
- `~20 minutes`
- `1 to 2 hours`
- `most of the day`
- `several days of travel`

Mark estimates as estimates when they depend on route, interruption, military movement, bureaucracy, weather, or another uncertain factor.

Do not invent precision that the runtime does not support.

## Strategic choices do not skip simulation

A wider-horizon option represents a plan, commitment, delegation, or objective. It does not silently complete days of persistent work.

If Wei chooses a week-long training program, the GM should translate that intention into the supported semantic actions, resolve them sequentially, refresh context after each write, and stop when a new interruption or player decision appears.

If Wei chooses a campaign objective, do not silently resolve mobilization, march, battle, occupation, and aftermath in one prose paragraph unless the runtime explicitly represents that as one semantic command.

## No menu after a declared action

If the player already supplied a clear action, resolve it. Do not answer with a list of alternatives before attempting the action. Carry that intent through obvious non-decision logistics such as preparation, departure, routine lawful travel, arrival, reporting, or taking the already-selected seat or post when those steps are implied and no material tradeoff appears.

If a new consequential choice arises during that sequence, stop at that new decision. After the action commits, refresh context and judge the actual endpoint. A fresh authored scene is not required for a menu when current exact state plus a presentation-only continuity anchor clearly establish that the declared sequence has reached a new player-facing fork.

## Choice language

Write choices in plain player-facing terms. Keep command names, IDs, payload fields, revisions, validators, and backend terminology out of the menu.

Prefer:
`1. Accept Ouki's preliminary review and prepare to leave for Kanyou.`

Avoid:
`1. Invoke career_status_resolution on char_ouki.`
