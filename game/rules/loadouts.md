# Loadouts and Equipment Standards

A unit may reference one standard loadout. Individual members store only explicit exceptions when practical.

Officer equipment remains independent of the subordinate unit standard.

Changing a standard does not magically refit the unit. Re-equipment requires conserved stock, transport, fitting, maintenance, familiarization, and training. If the intended standard remains identical, stock shortage may leave members temporarily under-issued against that one standard. If a subset is deliberately assigned a different standard, split that subset into a separate unit first. Never store two organizational loadout standards inside one aggregate unit.

Ordinary items with identical mechanics must reuse one catalog item. Do not create duplicate House-branded weapons solely for flavor. A standard sword includes its ordinary scabbard unless a scabbard later gains a genuinely independent mechanic.

## Standard versus actual issue

A unit's loadout field is its **intended organizational standard**, not a claim that every item is currently present and serviceable. Track temporary shortages, damaged or lost equipment, substitute issue, ammunition depletion, repair backlog, and delayed refit as actual issue/readiness/inventory state. These exceptions do not create a second unit standard. If a durable subset is intentionally assigned a different standard, split that subset into a separate same-troop-type unit before changing its loadout.

## Refit transition

A `SET LOADOUT` order changes what the unit is being refitted toward; it does not conjure equipment. If the new standard cannot be fully issued and familiarized immediately through a lawful time-advancing transaction, keep the current standard and create `refit_state.target_loadout_standard`. Reserve/transfer real inventory, advance fitting/maintenance/familiarization time, and track actual shortages/substitutes through issue state. When refit completes, make the target the current standard and clear the transition. If only a subset is changing standard, split the subset before creating the refit.
