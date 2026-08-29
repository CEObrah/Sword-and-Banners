# Combat and Warfare

Use this reference for personal combat, ambushes, skirmishes, formation fighting, battles, sieges, pursuits, withdrawals, and campaign-level military action.

The runtime owns every mechanical result. Narration must not turn a miss into a hit, a withdrawal into a rout, a wound into a death, or an unfavorable battle into a heroic success.

## Preserve causal legibility

For each material exchange, keep this causal order legible:

`declared intent -> observable initiation -> movement or formation response -> weapon/order interaction -> success, failure, or counter -> physical or organizational consequence -> changed battlefield -> next genuine decision`

Do not expose this as a numbered combat log. Render it as continuous lived action.

## Battlefield scene, not accounting dump

Combat resolution is not a ledger screen. After a committed personal-combat, skirmish, formation, battle, pursuit, or siege result, make the **primary IC presentation a grounded battlefield scene**. Mechanical numbers and state deltas may support the scene when they matter, but they must not substitute for showing what changed in the fight.

Translate authoritative combat state into what Tang Wei can lawfully perceive or receive through reports:
- changed distance, facing, frontage, pressure, cover, or ground;
- formations holding, bending, opening, reforming, advancing, withdrawing, or losing usable space only when the result establishes it;
- visible wounds, casualties, broken equipment, exhausted mounts, depleted missile fire, disrupted signals, command loss, or local disorder only when supported;
- the immediate consequence of Wei's action or order and the new threat, opening, constraint, or uncertainty it creates.

A useful combat paragraph answers **what happened, why it happened, what materially changed, and what Wei now faces** before offering any compact accounting recap. Do not lead with HP, casualty totals, readiness percentages, morale/cohesion values, formation counters, damage tables, or backend labels when the same truth can first be rendered as lived evidence. If exact numbers are decision-relevant and player-visible, give them concisely after or inside the scene rather than dumping the whole state object.

Scene-first does not authorize cinematic invention. If the runtime returns bookkeeping without enough detail to establish a charge, named death, rout, organ wound, terrain feature, enemy intention, command speech, or other specific event, do not manufacture one to make the prose exciting. Use only bounded connective detail compatible with the committed geometry and player-safe facts, preserve uncertainty, and say less rather than outrunning authority. Never turn an aggregate casualty delta into invented named deaths or a morale reduction into a fictional panic.

At battle scale, keep the camera with Wei's lawful command picture. He may see dust, standards, gaps, wounded streams, messenger traffic, pressure on a flank, or a sector changing shape when those are supported, but he does not gain an omniscient casualty ledger or enemy-state dashboard. Delayed reports remain delayed. Hidden enemy statistics remain hidden.

End a resolved combat beat on the **changed battlefield**, not on bookkeeping. When that change creates a genuine protected decision, return grounded options tied to the actual geometry, authority, and pressure. When the player's existing combat delegation still lawfully covers the next exchange, continue within that bounded span instead of manufacturing a menu merely because a resolver emitted another set of numbers.

## Mechanical combat invariants

Treat saved troop capability as mechanical truth at every combat scale. Aggregate formations derive rank-and-file capability from the actual cohort `skill_means`, `attribute_means`, experience, role, equipment, mounts, and current condition; readiness, morale, cohesion, formation integration, doctrine, command, terrain, and logistics modify how effectively that capability can be expressed but never replace it. A raw formation does not become veteran because its readiness or doctrine is high.

Weapon geometry remains causal after aggregation. Registered reach, minimum range, handling, delivered force, missile effective/max range, firing/reload cadence, shields/armor, mount quality, frontage, depth, terrain, cohesion, and contact compression determine which weapons can express their strengths. An ordered spear/polearm line can exploit reach while it preserves distance; cramped or disordered contact can push long weapons inside their useful range and favor shorter weapons. Never narrate a universal flat weapon bonus.

Missile ammunition is finite. Bows consume the registered arrow resource and crossbows consume the registered bolt resource. Ranged output is bounded by actual stock, carried load, cadence, firing duty, battle duration, range, and weapon/skill capability. Running out of ammunition removes or reduces the ranged contribution; it does not by itself make the entire formation unable to fight when a lawful melee fallback remains.

Do not average individually important people into the cohort mean. Exact people, `person-lite` members, commanders, deputies, staff, specialists, and other materialized standouts enter as separate bounded contributions and face separate role/exposure risk. Their bodies are either explicit extras to an anonymous institutional count or conserved materialized slots inside a cohort-backed formation according to saved ownership; never duplicate them. Exceptional people can matter greatly, but their contribution remains bounded and cannot turn one warrior into thousands of phantom soldiers.

Battle casualties must debit the same cohort/materialized bodies that fought. Surviving cohorts and participating materialized people may receive bounded role-relevant combat experience through the normal development law; battle never grants free rank-wide stats or advances the dead. Replacements enter as their own cohorts and retain their own capability until training/service changes it.

## Personal combat

Personal combat is continuous action-ready time, not alternating turns. Never narrate as though each character is owed one action before another can act again. Follow the runtime's timestamped causal trace: a short movement may complete before a slower strike, a fast recovery may create another action opportunity while an opponent is still committed, and a defense is available only when its reaction timing reaches the incoming contact. Do not convert these timestamps into arbitrary six-second or one-second rounds.

Stats above 200 remain mechanically meaningful. Do not narratively flatten an exceptional 230 skill/attribute to 200; the runtime may still bound what that capability can physically express through reach, frontage, equipment, fatigue, terrain, startup/recovery floors, and other real constraints.

Penetration and impact are not interchangeable narration words. Follow the committed contact chain exactly: incoming impact/penetration -> shield interception/perforation or failure -> residual force -> contacted armor channel/condition/angle -> residual body contact -> anatomical result. A spear or lance may perforate a shield without annihilating the whole shield; armor may prevent penetration while still transmitting blunt trauma; a catastrophic impact may break equipment. Never describe a weapon as "punching through" a shield, cuirass, barding, or bone unless the trace establishes penetration/failure at that layer.

Player combat intent may be coarse. A terse command such as **attack**, **press him**, **keep fighting**, or an explicitly delegated bounded combat span authorizes the runtime to fill only unspecified tactical details from Wei's standing doctrine, lawful perception, current geometry, equipment, fatigue, injury, and immediate battlefield state. This may include adaptive target selection when the player named no target, attack mode, anatomical aim, movement needed to make contact physical, and automatic defensive responses. Explicit player target, weapon/method, aim, restraint/lethal intent, disengagement, or other stated detail overrides doctrine for that detail. Do not require a separate delegation flag or a new player message for every strike, parry, block, dodge, or footwork adjustment inside the authorized span.

Do not narrate undeclared combat as repetitive best-action spam. The runtime's adaptive sequencing may change attack mode, target line, spacing, or defensive response because an earlier cut was parried, a shield repeatedly blocked one line, a target became disabled, or another opening became physically superior. Render the returned `attack_decision_reason` and aim as ordinary tactical behavior, not as an exposed score calculation. An explicit player method or target remains authoritative even when the adaptive planner would prefer something else.

At individual scale, make geometry and timing concrete when causal:
- distance and closing speed;
- facing and reach;
- footing and obstacles;
- cover and exits;
- allies, enemies, civilians, and witnesses;
- weapon readiness and grip;
- armor and shields;
- injuries, fatigue, and mobility;
- light, smoke, rain, mud, walls, furniture, animals, and elevation.

An injury persists through later exchanges. A damaged hand changes grip. A wounded leg changes movement. Lost equipment remains lost. Fatigue, blood loss, and armor burden matter when the runtime establishes them.

Irreversible anatomy is permanent saved state. If the resolver establishes a severed hand/arm/leg, destroyed eye, destroyed joint, or other absent/destroyed structure, ordinary rest, recovery, medicine, or passage of time may stabilize and heal surviving tissue but cannot regenerate the missing structure. Continue to respect its saved functional impairment in later combat and scenes.

For every meaningful exact-person attack, render the runtime's aim as part of the tactical action when it is known: the intended body zone/structure and the purpose of choosing it. Distinguish **aim**, **contact**, and **confirmed consequence**. It is valid to say Wei cut for an opponent's wrist because the trace establishes `aim_structure: wrist`; it is not valid to say the wrist was severed unless the contact/anatomy result establishes severance. Likewise, a cut aimed at an eye may be parried into a forearm contact, and narration must preserve that difference.

In multi-attacker personal combat, narrate the shared body state rather than presenting a chain of independent duels. Ordinary dodge, parry, and block draw on one cumulative whole-body active-defense load: each real response consumes reaction bandwidth, the load recovers continuously with the defender's reaction speed, and distinct attackers inside that recovery window add conflicting-source pressure. This load is separate from passive armor and from the physical readiness/orientation of a specific weapon or shield. When the trace establishes defensive saturation or displacement, make the cause concrete: Wei's weight is still committed from the first dodge, his blade remains outside the opposite attack line after a parry, his shield is turned toward the threat it just intercepted, a second attacker arrives before his body has recovered, a grapple occupies one or both arms, a fall has not yet reached ground contact, or an obstacle/body blocks the intended lane. Never narrate a second pristine defense when the resolver says its cumulative reaction load, weapon, shield, feet, posture, or position remain committed.

Treat released projectiles and already-committed body/mount momentum as independent physical events. If a shooter is incapacitated after release, the arrow or bolt still flies and may contact later. If an attacker is incapacitated before an unreleased melee contact, narrate the collapse/interruption instead of an attack that mechanically vanished. Near-simultaneous contacts may both land when the trace establishes that timing.

When structural anatomy or physiology is returned, describe only the structures and effects actually established. A severed tendon, opened major vessel, fractured bone, penetrated lung, airway injury, blood-loss progression, shock, or loss of consciousness is more specific than a generic wound, but the narration may not infer an unstated organ hit merely from severity. Permanent destruction/absence and continuing physiology remain distinct: an amputated limb is immediately nonfunctional while bleeding and shock may continue to change the fighter over subsequent seconds.

For named hero interventions inside mass battle, use the bounded local-contact trace and exact organizational consequences when available. Show the actual weapon/contact layers, incoming hazard, officer or signal disruption, local breach, artillery damage, or tactical gate/bridge seizure that the runtime committed. Do not translate hero pressure into fictional troop-equivalent bodies, and do not invent an objective consequence merely because a hero's generic disruption factor is high.

Tang Wei's saved `precision_function_denial` doctrine is mechanical targeting guidance, not narrator flavor. When the player has not named a specific target, the runtime may select exposed high-value structures such as the weapon hand/wrist, eye, ankle, knee, axilla/armpit, elbow/weapon arm, or neck according to authorized lethality and current physical state. Narrate the shortest efficient line actually returned by the trace; do not add flourishes, wasted feints, spins, or repeated low-value cuts that the resolver did not establish. Explicit player targeting overrides the saved doctrine, and lethal disposition of named/featured opponents remains protected player agency.

Never expose hidden rolls, enemy statistics, private intent, or exact capabilities Wei has not observed. Express uncertainty through trained observation: posture, breathing, equipment, formation, timing, scars, discipline, hesitation, known reputation, and previous behavior.

Protect Wei's agency during violence. Never invent lethal intent, mercy, surrender, dialogue, capture terms, or a decision to pursue a fleeing opponent. If the mechanical action requires one of those protected decisions and the player did not supply it, clarify.

## Skirmishes and retinue action

When dozens rather than individuals are involved, keep Wei's immediate command picture clear without trying to narrate every fighter.

Track what materially changes:
- line or cluster cohesion;
- local superiority;
- cover and choke points;
- signals and shouted orders;
- casualties or wounded leaders;
- mounts;
- ammunition and key equipment;
- routes of advance and retreat;
- civilian presence;
- prisoners and witnesses.

Zoom into individuals when a named person, local duel, broken point, rescue, command failure, or other event becomes causally important. Otherwise narrate units as organized groups.

## Formation battle

At formation scale, a formation is not one giant character and not hundreds of separate attack rolls in prose. Treat it as an organization with frontage, depth, cohesion, doctrine, command, morale, fatigue, equipment, supply, terrain interaction, and communication limits when supported by runtime state.

Keep these visible when causal:
- where each relevant formation is;
- what direction it faces or is moving;
- what terrain controls movement or visibility;
- what objective it is attempting;
- how orders reach it;
- how long movement or redeployment takes;
- whether reserves are committed;
- what happens to gaps, flanks, roads, gates, crossings, and high ground;
- whether casualties, fatigue, disorder, or command loss change behavior.

Do not give Wei an omniscient aerial map unless his position, scouts, signals, reports, and visibility support one. A commander often acts on delayed, incomplete, or contradictory reports.

### Reserves, resupply, and recovery inside battle

Keep two different meanings of "reserve" separate. A formation-level operational reserve is an uncommitted formation held for relief, counterattack, exploitation, or emergency commitment. Inside an already committed formation, its 1,000/500/100 command chain may instead rotate existing 100-person elements rearward to that formation's field HQ/baggage for sustainment. That internal rotation creates no new formation or bodies.

Missile troops begin contact with only their registered carried frontline load. Additional arrows/bolts in formation custody remain at field HQ/baggage and cannot appear in quivers by magic. A 100-person element can rotate rearward, draw only stock physically present there, spend deterministic service time away from contact, and return under its local commander when the line, higher orders, and tactical pressure make return sound. If HQ stock is empty or the line cannot safely release a hundred, ranged contribution stays depleted until real supply becomes available.

The same internal sustainment duty may replace battle-broken shields/armor only from conserved spare outfitting sets, remount cavalry only from formation-custody remount horses, and give the rotated element bounded fatigue recovery. Serviced people are temporarily unavailable to the fighting frontage during turnaround. Higher pressure can force quicker return; a stable line and capable 100-person command may hold a tired element rearward longer. Narration such as "fell back into reserve" should therefore identify what materially happened when known: relief, ammunition refill, equipment replacement, remounting, rest/reorganization, or a true operational reserve commitment.

### Persistent battle days and intervention boundaries

A persistent operational battle is not one atomic sunrise-to-victory roll. One `battle_resolve` settles only one bounded contact period. The shared campaign clock advances through that period so saved redeployment, messenger, daylight, and registered military/autonomy scheduler boundaries can become real before another contact is admitted. A local contact winner is therefore not automatically the winner of the wider battle. Reinforcements, intercepting forces, command changes, convoys, or autonomous campaign work may alter the next contact when their own lawful movement and scheduler work reaches the field.

Organized daylight contact normally ends no later than dusk. Dusk changes the operational posture to field-camp/security rather than silently simulating another night of daytime pressure. Troops remain where the operational geometry says they are; there is no teleport to a strategic base. During the night they may eat, rest, guard, reorganize, treat wounded through their actual owners, redistribute ammunition, refit from spare equipment, and remount only from material physically in custody. Dawn refit applies only to formations recorded as having actually camped through that night, never to a reinforcement that arrived just before dawn.

Night fighting is possible but never automatic. A new organized night contact requires the attacking formations to already carry a lawful aggressive battlefield order. While that exact night-contact window is active, combat pressure remains live only in its sector; other sectors retain camp/security recovery behavior. Darkness does not create a truce, so routs, pursuits, breakouts, camp attacks, siege actions, or deliberate night operations may continue when the runtime establishes them.

Field subsistence is represented by the canonical derived strategic-supply condition rather than ration inventories. Geography, route access, force size, mounted burden and civilian food stress can degrade movement, recovery, combat expression and mount condition at meaningful activity boundaries. Living horses and remounts remain exact conserved assets; no feed commodity is created or consumed.

## Orders and command

An order is a physical information event. It may require a runner, mounted courier, signal, drum, flag, horn, officer chain, written instruction, or prearranged doctrine. Distance and confusion can delay understanding.

Distinguish:
- Wei issuing an order;
- the order reaching a subordinate;
- the subordinate understanding it;
- the formation beginning execution;
- the intended military effect actually occurring.

Do not collapse these into one instantaneous event when the runtime or scene makes the distinction causal.

Command authority and administrative ownership are separate. Never narrate Wei commanding troops merely because House Tang owns or funds them if current authority does not permit it.

## Morale and cohesion

Do not treat morale or cohesion as abstract colored bars. Render supported changes through behavior: ranks compressing, men looking backward, officers repeating orders, standards wavering, cavalry refusing a bad approach, wounded being left, units reforming behind cover, soldiers responding to a familiar commander.

Never invent a rout, rally, desertion, panic, or heroic stand unless the runtime establishes it.

## Cavalry and mounts

Mounted troops occupy space, require room to accelerate and turn, depend on footing, and impose logistical costs. Horses tire, need forage and water, and can be injured or separated from riders.

Do not describe cavalry as teleporting through friendly infantry, walls, forests, dense streets, or impossible terrain. If exact mount consequences are runtime-owned, narrate only those returned.

Mounted impact is physical. When the trace exposes it, distinguish horse+rider+equipment mass, effective speed after load/barding/terrain, charge alignment, lance/weapon geometry, barding protection, opposing spear brace and actual body collision. A couched lance transfers mounted motion through the weapon; a ride-down/trample uses horse+rider collision rather than pretending the rider's sword became stronger. Shield walls and spear/phalanx-like lines exist only when actual shields, long weapons, order, depth and frontage support them; show them bending, holding, opening or breaking only when the committed formation method/result establishes it.

## Siege warfare

Sieges are labor, engineering, supply, disease risk, morale pressure, command, intelligence, and time before they are spectacle.

Keep causal distinctions among:
- investment and blockade;
- camp construction;
- reconnaissance;
- engines and works;
- sapping, ladders, towers, rams, fire, mines, or other supported methods;
- sorties;
- supply and relief attempts;
- negotiations;
- breach condition;
- assault readiness;
- assault execution;
- occupation or withdrawal.

A siege assault is a contested outcome. Preview may validate readiness but must not reveal the result. Never repeat preview to fish for a favorable assault.

Inside and outside the walls, make gates, towers, approaches, ditches, walls, camps, roads, water, stored food, relief routes, civilians, and command posts concrete when relevant.

## Campaign command cycle

Treat a major campaign as a command hierarchy, not as Tang Wei's nested army floating alone. Distinguish the sovereign/institution that legally owns the campaign order, the named supreme/campaign commander who may exercise that authority, Tang Wei's own field command, and Wei's subordinate command groups and formations. Superior command may give Wei exact campaign objectives and follow-on orders without transferring troop ownership or silently choosing Wei's protected tactics. Wei's lawful reports flow back upward through the same chain.

When fresh context exposes a `campaign_command` projection or a campaign-command interaction handle, use it as the human headquarters frame. A formal command conference should be staged as a people-centered scene with only exact attendees established by the runtime. Let commanders use the current campaign roster, lawful intelligence, maps/reports, supply picture, orders, authority boundaries, and actual military responsibilities. Do not invent attendance, a royal presence, a supreme commander, an army assignment, or an entry authorization because it would make the scene dramatic.

During an active campaign, dawn briefings and evening situation conferences are recurring command handoffs. The runtime's exact command snapshot, battlefield reports, after-action picture, current superior order, supply state, and known intelligence are source material. Render material changes through staff and commanders speaking, questioning, correcting, and arguing rather than reading a status object aloud. Compress a routine unchanged briefing; expand one that changes orders, reports casualties/contact, introduces a new commander, changes authority, exposes supply trouble, or creates a real decision.

A newly delivered superior order is its own causal scene. Put the actual commander/institutional chain and exact mission substance on screen before Wei responds or issues subordinate orders. Do not defer a material new order until the next dawn briefing merely because the daily cycle exists. The order is not automatically obeyed by prose: persist Wei's consequential execution, refusal, clarification, or protected tactical choice through the lawful command path when required.

Daily headquarters cadence never grants omniscience. A dawn or evening report can consolidate only what the relevant command actually knows from lawful reports and saved state. During battle, delayed battlefield reports remain the immediate tactical information channel; the command cycle organizes those facts at headquarters rather than replacing their delay or provenance.

A field-battle conclusion is not a reward screen. First surface the settled after-action picture and superior follow-on direction. When the campaign-command cycle exposes an `campaign_command_after_action_review` event, stage Wei's field headquarters accounting: subordinate reports, casualties and missing strength actually established, formation condition, ammunition/supply constraints that are known, the exact outcome, the current superior direction, and any already-saved service appraisal. Let staff disagree about interpretation when supported, but never invent casualty categories or blame. Merit appraisal, promotion, court reward, memorial/funeral consequences, prisoner disposition, territorial settlement, and campaign/war closure remain separate exact owners and should arrive in their lawful causal order.

## Campaign scale

A major campaign has a command rhythm above the battle itself. When fresh runtime authority exposes a campaign command cycle, preserve the chain from sovereign/institutional authority through the named supreme campaign commander to Wei's field command and then into his nested armies. Formal pre-campaign councils, lawful superior directives, Wei's upward reports, dawn field briefings, evening situation conferences, and post-battle/court handoffs are real causal events, not menu decoration. A superior directive may constrain mission, reporting, posture, or authorized objective, but it never transfers troop ownership, legalizes an otherwise unlawful frontier crossing, commandeers Wei's private House auxiliaries, or silently chooses Wei's protected tactics.

Royal-court councils and field-headquarters councils are distinct. In royal court, use the exact court session cast supplied by runtime alongside campaign commanders; in the field, use the current headquarters cast at Wei's actual location. Daily headquarters events must follow the field army rather than remaining anchored to the site of an earlier court conference.

At campaign scale, armies are moving institutions. Their effectiveness depends on roads, weather when causal, supply, forage, baggage, river crossings, replacement, intelligence, marching order, command relationships, political authority, garrisons, and time.

Do not narrate a strategic redeployment as a sentence-long teleport. If the runtime resolves travel or formation movement over days, preserve the time and potential interruptions it commits.

A victory can create new burdens: prisoners, wounded, damaged equipment, exhausted troops, occupied ground, exposed supply routes, political expectations, and the need to replace losses. Preserve only runtime-supported aftermath.

## Camera scale

Choose the smallest camera that explains the causal event:
- duel: bodies, weapons, timing, footing;
- skirmish: immediate groups, terrain, signals;
- formation action: fronts, flanks, reserves, order flow;
- battle: sectors, objectives, reports, commitment of forces;
- siege: works, walls, supply, relief, command;
- campaign: roads, armies, supply, territorial objectives, information delay.

Zoom inward for a decisive named action and outward when the organization becomes more important than any individual exchange.

## Contested preview security

Sword protects contested outcomes from preview probing. `battle_resolve`, `personal_combat`, and siege assaults may return readiness without projected outcome. Treat that as intentional.

Never:
- call preview repeatedly hoping for a different result;
- infer hidden random output from timing or metadata;
- narrate a contested result before execute commits;
- change intent after seeing a result while pretending it is the same command.

A contested action is sampled and resolved once during execution.

## Aftermath

After violence, register only persistent consequences the runtime supports, such as:
- wounds and deaths;
- missing or damaged equipment;
- casualties and replacements;
- fatigue and cohesion;
- prisoners or custody;
- witnesses and evidence;
- damaged fortifications or assets;
- territorial control;
- reports and political obligations;
- changed relationships or reputation;
- supply expenditure.

Do not add cinematic casualties or destruction merely to make a scene feel expensive.


## Persistent operational battlefields

When a large battle spans multiple sectors or continues while formations redeploy, use the runtime's operational battlefield layer rather than resolving the whole field as one contact. The battlefield belongs to an existing `sword-operation`; it owns sector geometry, formation assignment, orders, timed redeployment, local pressure, and communication/report delay. It does **not** own casualties, wounds, exact combat outcomes, territory, sovereignty, or manpower creation.

Treat a formation moving between sectors as physically unavailable at both sectors until the saved redeployment completes. Other sectors and autonomous actors continue while Wei moves, fights, waits, or receives delayed messages. Resolve actual contact through the existing battle/personal-combat authority only when the saved battlefield geometry permits the contact, then reconcile its consequences back into the operational picture exactly once.

Player knowledge follows sight, command presence, scouts, flags, horns, couriers, and delivered reports. Never expose raw enemy-sector pressure merely because the runtime stores it. A battlefield report can interrupt time advancement when it creates a genuine player-facing command decision; maintenance-only pressure changes do not require a menu.

## Personal combat environment and command scale

Personal combat consumes the same deterministic current environment authority used by travel and warfare. Footing can affect agility/coordination and weather can affect ranged weapon effectiveness only through registered runtime mechanics. Narration must not add a second rain, mud, wind or visibility modifier.

Keep scale explicit: exact fighter -> persistent retinue/command group -> formation -> battlefield/campaign. A retinue organizes command relationships and familiarity but owns no additional bodies. Named officers and specialists may matter locally without being converted into fictional troop-equivalent bonuses.