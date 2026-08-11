# Player Interface

Natural language is the player interface. The player should describe what Tang Wei wants to do in ordinary language. ChatGPT translates that intent into the current runtime's semantic command surface.

## Interaction modes

Unlabeled gameplay text is normal in-character play.

`IC:` explicitly marks in-character gameplay.

`OOC:` is read-only discussion, planning, explanation, inspection, comparison, feasibility, or hypotheticals. Do not mutate campaign state or advance time merely because an OOC discussion occurred.

`OOC DEV:` is development or maintenance of the runtime, rules, repository, deployment, Skill, or integration. It is not gameplay.

A message can contain multiple blocks. Resolve them in order.

## The player does not write commands

Never require the player to know command names, JSON payloads, revisions, request IDs, repository paths, or schemas.

Internally, a consequential action follows:

`natural-language intent -> fresh play context -> one current semantic command -> preview -> exact execute -> fresh context -> narration`

If the runtime cannot represent a persistent action, explain the limitation OOC rather than pretending it happened.

## Do not edit campaign JSON manually

Normal gameplay must never ask the player to edit campaign JSON manually. Persistent mutations belong to the runtime's semantic command and transaction systems.

OOC DEV repairs should also avoid casual direct state edits. Confirmed bad campaign truth should use an explicit repair or migration path with provenance.

## Read tools

Use `get_play_context` first for every live turn. It is the bounded entry point for current state and command capability.

Use `get_person_sheet` only with exact person IDs permitted by fresh context.

Use `inspect_game_object` only with exact object refs permitted by fresh context.

Use `ooc_audit` for read-only diagnostic questions when relevant.

Never guess hidden IDs to browse the repository through the MCP surface.

## Writes

Each persistent write is one semantic command.

A new command gets a fresh request ID and uses the exact expected revision returned by fresh context.

`preview_command` is read-only. It validates the proposed semantic command and returns the complete command object plus a short-lived preview attestation when executable.

`execute_command` receives the exact previewed command and matching attestation. Do not reconstruct either one.

After committed or duplicate execution, refresh play context before narrating persistent aftermath.

## Contested actions

Sword protects contested combat from preview probing. A battle, personal combat action, or siege assault can have a valid preview that exposes readiness but not outcome.

The player does not need to interact differently. ChatGPT handles the distinction internally and executes the declared action once when the player has committed to it.

## Multi-step intent

A natural-language request can imply several runtime steps. Carry intent through obvious prerequisite logistics only while no new material choice appears.

Example:
`I accept the review and go to Kanyou.`

This may require answering, departure, travel, arrival, and the appointment boundary if each step is supported. Resolve them sequentially, refreshing after each write. Stop if the road closes, a new order arrives, a cost appears, a dangerous route choice emerges, or another consequence creates a new decision.

## Player-facing mechanics

During ordinary play, present mechanics through lived consequences. Exact mechanical detail is appropriate when the player asks OOC or when a number is itself relevant to the decision, such as money, personnel, travel time, casualties, supplies, or authority.

Do not expose OAuth, Git hashes, revisions, request IDs, attestation strings, command payloads, or validators in IC narration.

## Freedom of action

Choice menus are examples, not limits. The player may ignore them and type any natural-language action.

Do not reduce play to repeated menus when the world can continue naturally. Let NPCs finish speaking, let committed actions resolve, and surface choices only at genuine decision points.

## Actionability of restrictions

A mechanically correct refusal is not a complete player interface when the player cannot tell what must change. When fresh runtime context exposes a safe readiness or eligibility reason, explain who or what is blocked, why it is blocked, and the known condition or time at which it can become available again. Do not expose hidden state to explain a restriction.

Treat recurring opaque rejection as a runtime-interface defect worth surfacing through the live-play review loop. Do not make the player discover required enum values, nullable fields, custody conditions, readiness rules, or legal prerequisites by repeated failed guesses when the runtime can safely advertise them.
