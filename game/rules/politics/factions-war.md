# Politics Module: Factions War

## Faction decision procedure

A faction action requires:

1. goal or pressure;
2. knowledge with confidence;
3. authority or internal coalition;
4. people, money, stock, route, and time;
5. expected benefit;
6. risk and alternatives;
7. order and implementing actors.

Factions do not attack merely because they dislike Tang Wei. Internal factions, officers, households, and local elites may resist or reinterpret policy.

## Small-faction and irregular ecology

Bandits, smugglers, rebel cells, mercenary splinters, village militias, cult networks, and deniable armed groups require concrete causes such as crop failure, displacement, deserters, debt, protection rackets, feud, outlawed belief, political patronage, predatory leadership, or paid violence.

Each persistent small faction stores origin pressure, combatants, support personnel, dependents, wounded, food and water, weapons and transport, informants and bribes, routes or territory, morale, leadership, internal disputes, lawful and criminal income, current opportunities, threats, recruitment sources, and exit options.

## Faction resources, internal approval, and implementation

After choosing a goal, a faction must secure an implementing coalition and assign exact actors. A policy record separates decision from execution: `proposed -> approved_or_ordered -> funded -> communicated -> begun -> completed_or_blocked_or_abandoned`.

At each stage, opponents may delay funds, alter orders, withhold troops, leak information, appeal, resign, defect, or comply. A charismatic leader cannot spend an absent treasury or move a force outside command. A council cannot execute a plan without officers, clerks, messengers, routes, and time.

## War goals

Every war or armed campaign records one or more goals: border adjustment, tribute, hostages, succession, rebellion suppression, trade access, punitive raid, prisoner recovery, annexation, independence, claimant installation, restoration, rival-house destruction, or protection.

Victory is measured against the goal, not total map destruction. Campaigns can end through battle, siege, blockade, negotiation, exhaustion, political collapse, assassination, defection, or changed priorities.

## Rebellions, invasions, sieges, and strategic event lifecycle

Rebellion requires a constituency with grievance, organization, leadership or coordination, communication, recruits or armed supporters, supplies, a political objective, and a trigger or deliberate order. Low loyalty alone does not spawn rebels. Invasion requires a war goal, command authority or coercive control, reachable forces, muster, route, supply, transport, intelligence, and a departure order. Siege requires an attacker that reaches and invests a defended site with enough force and supply to maintain sectors; declaring a siege on a map does nothing.

Each conflict event owns: sponsor, participants, goal, pressure source, legal claim or criminal basis, knowledge, preparation, assigned forces, treasury and supplies, routes, timetable, opposition, civilian exposure, success and abort conditions, current stage, and next review. Stages are `latent_pressure`, `advocacy_or_intrigue`, `organizing`, `preparation_blocked`, `mobilizing`, `active_operation`, `contact_or_siege`, `settlement_or_aftermath`, and `terminal`. The same complete state always produces the same next stage.

An event may shrink, split, merge, be exposed, receive support, lose leaders, change goals, negotiate, disperse, or be preempted. Famous history supplies pressures and likely actors but never bypasses the lifecycle. Player travel does not cause distant wars to exist; it may reveal an event already produced by its own causes.

### Regional pressure portfolio and player opportunity

The save maintains only a compact set of causally important pressures, not hundreds of random events. Each pressure has a stable owner, stage, severity, possible organizers, resource readiness, route access, authority or coercion, blockers, discovery paths, and next review. A review may advance at most one stage unless an exact decisive event supports more.

Player opportunity is separate from event existence. After discovery, compare travel time, route condition, authority, and the remaining time before the event's next stage. The player may arrive before contact, during a siege, after a battle, or too late. The game must not freeze an event simply to wait for Tang Wei.

## War capacity and exhaustion

A campaign tracks war goal progress, field forces, garrisons, casualties, prisoners, treasury, debt, food, transport, horses, officer losses, civilian harm, occupied territory, allies, legitimacy, and political deadlines.

War capacity uses the minimum-gate formula in `game/data/mechanics/politics.json`.

War exhaustion is not a single morale bar. Store supported pressures by constituency: troops, households, taxpayers, merchants, elites, allies, occupied civilians, and leadership. Casualties, arrears, conscription, lost harvests, defeat, blockade, refugee burden, and broken promises raise relevant pressures. Victory, pay, relief, captured objectives, negotiated terms, rotation, and credible purpose may reduce them. Exhaustion changes willingness, compliance, recruitment, taxation, desertion, and peace positions; it does not automatically end war.

## Peace and negotiation

Peace may exchange land, money, prisoners, hostages, marriages, titles, recognition, trade rights, military restrictions, office, vassalage, oaths, or withdrawal schedules. Terms require signatories with authority, enforcement, witnesses, and transfer procedures.

A party may comply, delay, violate, reinterpret, or lack capacity. Breach creates evidence and consequences rather than erasing the agreement.

## Mass mobilization, claims, and coercive consequences

A rebellion or state summons identifies the manpower layer, province, authority or organizer, message network, requested number, reporting places, deadline, route, promised or coerced service, support plan, and equipment source. Sympathizers, eligible civilians, and claimed supporters are not active troops.

Large-number claims retain speaker, audience, date, confidence, and motive. Officials may count military households, registered troops, servants, laborers, allied contingents, or people merely summoned; rebels may count followers and families. Exact host ledgers keep arrived, armed, formed, effective, and camp totals separately so propaganda never changes combat.

## automatic regional and global arcs

Every faction, pressure, and historical trajectory retains goals, resources, blockers, stage, and next review. The engine processes crossed clocks without player prompting. Global movements create concrete local sub-events - messages, organizers, arrests, recruitment, shortages, refugees, patrols, mobilization, or conflict - while Tang Wei learns only through valid information paths.

## executable faction action gate

A faction action evaluates authority, people, money, supply, route, information, time, and implementation capacity separately. The action is eligible only when every required gate meets its saved minimum. Mean readiness may compare alternatives but cannot hide one failed essential gate. A failed gate records the blocker and next actor rather than creating partial effects without a method.

