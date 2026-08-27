# Organization and Formation Law

## Authoritative military chain

The persistent military chain is:

`population -> force/cohort manpower -> persistent formation -> zero-body command group / temporary operation or battlefield arrangement`.

`state/forces/` and House/private force owners conserve military bodies and reserves. `state/formations/` contains the persistent independently orderable fighting organizations that receive those conserved bodies. A formation owns its current fighting allocation through exact force/cohort links and may contain several troop roles in one durable organization. A command group owns hierarchy and authority only. An operation, battle sector, siege assignment, march column, or other temporary arrangement references these exact owners and never creates another pool of soldiers.

A **Unit** is an establishment class of a persistent formation, not a separate writable `state/units/` object. `runtime/sword_runtime/unit_establishment.py` owns Unit establishment geometry. A Unit has at least 500 authorized fighters and its authorized fighting strength is a multiple of 500. Smaller persistent independently orderable formations are detachments.

A persistent formation has one top commander outside its stated fighting strength. Internal 1,000/500/100 command bodies are conserved inside that fighting strength and may exist only below the formation's own command echelon. Succession and staff appointments are separate.

## Mixed-role persistent formations

A persistent formation may contain multiple troop roles when that is its durable organization, for example infantry, crossbowmen, archers, and cavalry under one formation command. `composition`, cohort slices, establishment composition, equipment custody, mounts, ammunition, readiness, morale, cohesion, fatigue, experience, doctrine, location, and current command all belong to or are derived from the exact current formation/force authorities.

A formation exists because a body of troops needs durable independent command, assignment, readiness, history-relevant experience, or organization. Do not materialize one persistent formation for every embedded 100/500/1,000 command echelon.

Force-pool manpower cannot fight as a free-standing abstraction. It must be lawfully allocated to a real formation before tactical use.

## Split, merge, reconstitution, and losses

`formation_split` and `formation_merge` conserve real personnel, cohort provenance, role composition, equipment, mounts, ammunition, fatigue, morale, cohesion, injuries/materialized people, and command relationships according to their runtime owners. A split cannot silently select superior troops unless a lawful selection rule supplies that evidence.

`authorized_strength` is establishment authority, not a copy of current surviving headcount. Casualties can leave a Unit understrength without shrinking its authorized establishment or erasing surviving internal officers. Reconstitution draws only from lawful replacement manpower, equipment, mounts, money, supply, and training capacity. It never resets casualties or creates bodies.

Returning or reassigning a formation changes custody/command/location as authorized. It does not restore lost people or materiel and it does not transfer institutional ownership unless an explicit rule does so.

## Command hierarchy

`game/data/mechanics/command.json` and `state/cmd/command-groups/` own recursive command organization. A command group is a zero-body node with one real commander, optional explicit staff and successor order, direct formation elements, direct named people where lawful, and subordinate command groups. One subordinate command group consumes one direct parent command slot regardless of descendant depth. Descendant formation bodies do not become direct parent manpower merely because the parent retains strategic authority.

Nested armies therefore remain intact when attached under a larger field army. They are not flattened into a second formation list and their descendants are never duplicated. Tang Wei's player-controlled formations use the same hierarchy and capacity rules as world-owned forces.

Command capacity is deterministic from the current commander, direct personnel/slots, staff and communications, doctrine familiarity, health/fatigue, terrain/dispersion, information quality, and lawful authority. Command skill affects command/control and decision quality. It does not become a hidden multiplier to each soldier's body or weapon capability.

## Commander physicality and succession

A commander is always a person. If physically present, that person can move, fight, be wounded, become exhausted, be isolated, captured, killed, or routed. A commander at headquarters is not automatically exposed to frontline contact, while a commander who personally enters a charge accepts the resulting physical exposure.

Command loss is resolved through saved deputies, succession, standing doctrine, communication state, and current hierarchy. If a superior directly absorbs orphaned formations, the superior's direct command load changes immediately.

## Formation identity and army cohesion

Persistent formations retain identity through veteran continuity, shared service, commander bonds, doctrine familiarity, experience, morale, cohesion, reputation-relevant outcomes, and current losses. These are current causal facts or compact accumulators, not append-only diaries. Temporary operation/battle arrangements do not become competing identity owners.

Army and formation identity may affect morale, willingness to endure, command trust, desertion/mutiny pressure, and recovery where registered mechanics consume it. Identity never creates people, equipment, knowledge, or combat capability by itself.

## Support, logistics, and field duties

Engineering, signals, baggage handling, casualty collection, scouting, camp security, resupply, and similar work use existing people, equipment, animals, facilities, routes, time, and supply. Support labels never mint separate hidden manpower. Army trains and fortified-site logistics materialize only when strategically relevant and remain linked to conserved source assets.

## Materialization of important people

Large ordinary forces remain cohort-first. A named officer, specialist, standout, casualty, prisoner, or recurring individual materializes only when individual identity becomes causally important. Materialization consumes or reclassifies one already-conserved body and preserves source-cohort provenance. It never creates a replacement body.

## Household, state, personal, allied, and mercenary ownership

Command and ownership are separate. State troops, House troops, Tang Wei's personal force, allied formations, and mercenary companies retain their own institutional ownership while assigned under another commander unless an explicit lawful transfer changes ownership.

Household or other non-sovereign organizations do not receive troop strength merely by existing. An armed branch must use an exact force/formation owner and conserved source manpower. Generic institutions may remain lightweight until their money, membership, facilities, command, or force activity becomes materially relevant.

## Player agency

World-owned forces retain lawful home authority and autonomous agency. Tang Wei controls only formations, command groups, people, or resources actually assigned or transferred to him under current authority. OOC discussion and previews never create organization, deployment, doctrine, or command intent.
