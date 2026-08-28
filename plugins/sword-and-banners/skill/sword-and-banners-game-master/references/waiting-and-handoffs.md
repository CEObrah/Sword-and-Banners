# Waiting and Causal Handoffs

Use this reference when Tang Wei is waiting for an external reply, summons, courier, institutional disposition, delayed report, or other future dependency, especially after completing a local objective away from his ordinary base.

## Waiting is an interrupt condition

Treat `wait for X` primarily as permission to let **X interrupt ordinary life**, not as an automatic instruction to remain physically motionless at the current location.

Separate two questions:
1. what future event or condition ends the waiting policy;
2. where and how Wei spends the interval.

If the player explicitly says `hold here`, `remain in Kanyou`, `stay at the camp`, or equivalent, preserve that physical posture. If the player says only `wait for the staff's answer`, `await the courier`, or equivalent, do not infer either `stay here` or `go home`.

Travel destination remains protected player agency. When the current place is plainly a temporary venue and no saved plan already determines Wei's next location, hand back that one meaningful choice before advancing substantial time. Ground the options in fresh player-visible facts: for example return to an established home/base, remain locally, travel to another already-known destination, or Free Action. Do not invent a destination merely to fill a menu.

## Waiting should coexist with ordinary life

Once the interval location and routine are explicitly chosen or already lawfully established, let the waiting policy run over ordinary life rather than turning Wei into an idle placeholder. Preserve saved training routines, House duties, rest, meals, equipment care, administration, or already-declared travel when the runtime supports them. The awaited dependency becomes the interrupt condition.

Use causal chronology until one of these occurs:
- the named response/report arrives;
- a known deadline or clock boundary matters;
- a high-salience wake interrupts;
- fatigue, supply, access, safety, money, or another condition creates a new tradeoff;
- the chosen waiting policy reaches its endpoint.

Do not manufacture menus every day merely because time passed. Do not silently add unrelated commitments.

## Actionability-filtered standing waits

A runtime-delivered player-facing event is a causal handoff, not automatically the endpoint of the player's standing wait. When the player's declared threshold is `until I can act`, `until something actionable happens`, `until there is a real decision`, or an equivalent actionability condition, inspect the newly delivered player-visible facts before ending the wait.

Treat the event as **interim** and carry the same standing policy forward when it establishes only background movement, broad material activity, confirmation of already-known facts, or incomplete information that gives Wei no materially distinct action, commitment, authority choice, information-gathering choice, resource tradeoff, or protected decision beyond continuing the existing wait. Do not end the turn merely because `advance_time` stopped at such an event, and do not fabricate a menu to justify the stop.

Treat the event as a **terminal handoff** for that wait when player-visible facts establish at least one concrete course Wei can now choose among, a new protected decision, a hard authority/resource/safety boundary, or a materially different information-gathering opportunity. At that point, if the player's current message has not already supplied the response, load `choices.md`, narrate the decision-relevant facts first, and provide grounded choice scaffolding before ending.

This actionability filter never suppresses a true hard wake such as direct hostile contact or another runtime-defined causal state whose settlement cannot lawfully continue without Wei's immediate response. A command/office offer, commission, or similar voluntary choice is normally a terminal handoff for an `until actionable` wait, but it remains a durable decision in its exact owner rather than a scheduler lock unless an independent hard causal boundary also exists. The filter only prevents non-decision reports from becoming artificial turn boundaries.

## Choice wording must include physical implications

A menu option is authorization only for what it actually says. Never write `Withdraw and wait for formal direction` and later treat it as authorization to remain in the current city, return home, relocate an escort, or begin a new routine.

If the intended option includes relocation, say so before the player selects it, for example:
- `Withdraw, return to Tang Manor, and await the staff response there.`
- `Remain in Kanyou and await the staff response locally.`

If relocation is intentionally left open, resolve the withdrawal first and then scaffold the travel decision once.

## Contact before petition

Treat access-seeking and substantive business as separate causal stages.

A location-targeted `seek_contact` means only that Wei is trying to find the proper receiving person, office, or channel. It must never be narrated as if a petition, offer, request, report, or political position has already been delivered to an unseen institution. In particular:
- do not turn `seek_contact` into quoted substantive dialogue unless the player explicitly supplied those words for the contact attempt;
- do not say that an office "received the request", "has the proposal", "is considering it", or will answer when no exact receiving handoff exists;
- do not convert arrival in a city into institutional access merely because an institution exists there.

When the runtime later establishes an `audience_response`, receiving officer, audience, clerk, commander, council, or equivalent access handoff, narrate that meeting first. The subsequent petition/request/report is a distinct player action unless the player had already explicitly delegated that exact immediate communication. A hearing is not acceptance, a request is not a decision, and waiting for access is not waiting for the eventual substantive answer.

If the player says they intend to meet someone and then make a request, carry the sequence forward causally: seek access -> establish the receiver -> stage the meeting -> let the actual request occur at that receiver. Never collapse those stages into a request spoken "to the air".

## Scheduled councils and pre-convening projections

A player-safe campaign-command projection may expose a pre-convening state such as `pending_registration` before the exact campaign-command cycle has been registered by causal chronology. Treat that as a projection/lifecycle state, **not** as a claim that Tang Wei personally needs to register, petition for access, or perform a zero-time interaction to make the council exist.

When fresh context establishes all of the following:
- Tang Wei is already listed among the campaign council's participant commanders;
- the council venue is established and Tang Wei is already at that venue, or the player has explicitly authorized the required travel;
- the player says to `attend`, `go to`, `report for`, `wait for`, or otherwise proceed into that scheduled council;

then carry the declared intent as a standing attendance/wait posture through causal chronology. Do **not** use `interaction_action` merely to "register", "enter", or "proceed" against the synthetic campaign-command cycle. Use the supported `advance_time` path with a narrow semantic stop condition for the council or its directly relevant player-facing campaign-command event, preserving the player's explicitly chosen location and ordinary routine while waiting.

The runtime remains responsible for registering/scheduling the exact council host, moving lawful NPC attendees through real travel delay, committing the convening event, establishing actual presence, and applying any formal command consequence. Never narrate the council as underway before that event commits. If chronology instead exposes a real access problem, authority dispute, hard wake, or other material tradeoff, stop there and return agency normally.

If the projection is pre-convening but no causal council lifecycle appears after lawful chronology/synchronization, treat that as an OOC development defect rather than inventing a player registration ritual.

## Institutional follow-ups

An interaction attempt never fabricates a response. If the runtime exposes an already-routed institutional follow-up or other causal dependency, ordinary life may proceed until that route settles. Narrate only the resulting player-visible event when it is actually established.

If no durable follow-up exists, do not pretend one will inevitably arrive. Keep the larger objective visible, allow lawful attempts or waiting, and flag the missing causal lifecycle as an OOC development issue when it materially blocks play.
## Semantic stop criteria

When the player names several distinct reasons that would end a wait, treat those reasons as alternatives unless the player explicitly says all must be true. For example, `wait until entry authority changes, material military intelligence arrives, or hostile contact occurs` should wake on the first matching reason. Encode each precise reason as one conjunctive semantic clause and place distinct alternative reasons in `wait_policy.any_of`; values inside one criterion field are alternatives. Do not flatten a precise source+topic condition into a broad OR, and do not fall back to `stop on any notice`. Unrelated reports may be recorded without breaking the standing wait.

