# Personal, Ranged, Mounted, and Heroic Combat

`data/mechanics/core.json` owns resolution order and deterministic RNG. `data/mechanics/body.json` owns body geometry. `data/mechanics/combat.json` owns personal, ranged, mounted, fatigue, recovery, handling, contact, wear, and heroic numerical formulas. `data/mechanics/injury.json` owns protection, wound, bleeding, shock, and structural-injury calculations.

This file defines legality, sequencing, state ownership, and causal interpretation. It must not redefine numerical tables owned by the structured registries.

## Resolution order

A consequential combat action follows the global core sequence. Geometry and target acquisition are resolved before control. Resource expenditure and timing occur before contact. A legal defense is selected before the control margin is calculated. Protection and anatomy are resolved only after a contact exists.

A result cannot skip fatigue, condition loss, ammunition, body position, injury, or elapsed time merely because the narration is short.

## Current usable capability

Permanent attributes and skills are not copied into temporary combat values. Current readiness, fatigue, relevant injury impairment, body load, equipment condition, stance, and legal position modify execution through `data/mechanics/combat.json`.

No modifier may be applied twice under different names. Combat experience uses the registered experience modifier once.

## Load, exertion, and recovery

Every carried or worn item contributes to current body load when physically carried. Hand-held, ready-carried, packed, worn, tack, barding, rider, cargo, and mount loads remain distinct so they can affect the correct actor.

Every positive-duration combat segment is classified into a registered exertion or recovery state. Raw fatigue accumulates before persistence rounding. Recovery requires actual time and conditions. A combat segment cannot close with unchanged fatigue unless a recorded recovery segment exactly offsets the gain.

Equipment carriage balance, heat, terrain, injury, and load use the factors in `data/mechanics/combat.json` only when physically relevant.

## Geometry, reach, closing, and hand occupancy

Current height and mass come from body state. Weapon reach comes from the item profile plus the registered body adjustment. Reach affects whether a threat can contact and the control advantage before contact; it never multiplies damage.

Hand occupancy is physical. A hand already committed to a shield, weapon, climbing surface, restraint, casualty, or other object is unavailable. Two-handed weapons require both usable hands unless a registered method explicitly changes the grip.

The registered formation spear-and-shield methods are legal only while their formation, spacing, shield state, and adjacent support requirements remain true. They cease to apply when the formation opens or the actor loses the required physical arrangement.

## Perception and initiative

An actor may respond only to threats that have been perceived or validly warned about. Concealment does not teleport an attacker or remove route/time requirements. Detection margins use the registered combat/perception bands and never grant future knowledge.

Initiative is local timing, not a permanent turn-order entitlement. Startup, travel distance, weapon recovery, awareness, surprise, and declared guard all matter.

## Attack, defense, and contact

Attack Control, Dodge Control, Parry Control, Block Control, handling adjustment, combined pressure, contact grades, and contact multipliers are owned by `data/mechanics/combat.json`.

Before calculation:

- confirm the attack method is physically legal;
- confirm required hands, grip, posture, reach, clearance, ammunition, mount state, and equipment;
- confirm the defender has a legal defense line;
- identify the actual body/item geometry exposed.

A defender may dodge only when a displacement lane exists. A parry requires a ready legal weapon line capable of redirecting the incoming geometry. An active block requires a held shield in the incoming arc. Passive or planted shields may intercept only according to their registered state and arc.

Exact ties favor the defender or current controller unless another registered subsystem explicitly says otherwise.

## Multiple attackers

Only attackers with a real lane, timing window, weapon line, and target access contribute. The combined-pressure formula is registered in `data/mechanics/combat.json`. Crowding may prevent later attackers from contributing at all.

A group does not gain pressure from bodies that cannot physically enter the contact.

## Grappling and restraints

Grappling requires actual contact. Hold and escape scores use registered combat/body formulas. Mass affects control through body mechanics but does not replace Strength, technique, leverage, or position.

Pins, joint controls, chokes, restraints, carrying, dragging, and throws require the corresponding geometry and available limbs. A successful control result changes exact body position and legal future actions.

## Falls, throws, trampling, and collisions

Falls and collisions resolve from actual mass, vertical distance, relative speed, surface, orientation, bracing, and legal breakfall response through the registered body/combat formulas. Armor may reduce transmitted injury but its mass already contributes to the fall or collision and is not counted twice.

Horse/rider collision uses the actual horse, rider, equipment, speed, alignment, target mass, and contact geometry.

## Melee force, weapon recovery, and condition

A contact converts the user's current Strength, weapon pattern, motion, technique, condition, legal grip, and contact grade into the registered attack channels. Cut, thrust, and blunt transfer are resolved separately.

Weapon recovery is a real time/control state. A weapon that has not recovered cannot make another full legal action merely because the narration moves quickly.

Condition is continuous for exact consequential equipment. Display condition bands are UI groupings only.

## Shield and armor resolution

A shield is resolved before armor only when the incoming line actually intersects the shield's current arc and state. A successful interception may still transmit impact.

Armor resolves only on the body region actually contacted. Ordered layers contribute according to their channel resistance, condition, fit, angle, and registered layer contribution. A stopped edge or point can still transmit blunt trauma.

Armor never becomes whole-body protection unless its item geometry actually covers the struck region.

## Anatomy, injury, bleeding, and shock

Wounds use `data/mechanics/injury.json`. Contact severity, substructure, bleeding, pain, blood loss, shock, functional impairment, consciousness, treatment, infection, and recovery remain separate state.

Death requires irreversible anatomy or a registered physiological process crossing its threshold. Named status, player importance, plot importance, or narration does not alter mortality.

## Weapon and equipment damage

Every relevant hard contact may damage the weapon, shield, armor, harness, tack, barding, or other contacted equipment. Condition loss, overload, structural capacity, and failure thresholds use the registered combat/injury formulas.

Repair requires actual labor, parts, tools, workspace, cost, and time. Repair never creates quantity.

## Fire, smoke, and environmental hazards

Fire, smoke, water, mud, cold, heat, confined spaces, falling structures, and similar hazards require actual geometry and duration. Environmental effects use the same injury, fatigue, visibility, and movement systems rather than bypassing them through narrative severity.

## Ranged and crossbow combat

Range bands, draw completion, retained force, ranged control, projectile impact, cycle factors, movement factors, ammunition access, and recovery are owned by `data/mechanics/combat.json` and the item catalog.

A bow cannot exceed its physical draw power because the archer is stronger. A deliberate shot is illegal below the weapon's stable draw requirement. A crossbow requires a verified full latch before using its registered projectile output.

Flight fire requires an area target and cannot select one exact person unless another registered method supplies that capability.

Ammunition is consumed on release. Resupply consumes route and handling time. Projectiles do not reroll contact after release.

## Mounted combat

The horse and rider are separate bodies with separate health, fatigue, equipment, load, and injury state.

Mounted control, horse load ratio, effective speed, charge alignment, panic control, horse fatigue, and collision index are owned by `data/mechanics/combat.json`.

A mount must be physically fit and trained for the declared method. Tack and barding affect control, load, heat, articulation, terrain, and protection through their actual profiles.

Mounted weapon compatibility modifies difficulty. It does not create or remove hands. A rider cannot simultaneously use equipment whose physical hand requirements conflict.

## Heroic personal action in mass battle

Exceptional individuals remain bound by the same body, timing, fatigue, contact, injury, weapon, and lane rules. Heroic tempo and minimum action interval are registered in `data/mechanics/combat.json`.

One action creates at most one primary contact unless a specific registered method defines a different physical effect. Multi-opponent throughput comes from actual repeated legal actions and available lanes, not a narrative sweep multiplier.

A named person has no aggregate immunity inside a formation.

## Receipts and compaction

Featured-character contacts, severe wounds, deaths, captures, disputed calculations, structural failures, command collapses, and player-requested logs retain reconstructable receipts. Routine formation contacts may compact after their state effects commit, but must preserve enough aggregate input/output data to reconstruct manpower, equipment, ammunition, fatigue, morale, and casualty deltas.

No receipt compaction changes the already committed physical result.
