# Politics, Law, and Factions




Numerical authority for coalition weight, occupation reach, legal finding margins, war capacity, schemes, exposure, and evidence weight is `data/mechanics/politics.json`. This file owns the legal, political, procedural, and causal interpretation around those numbers. `RUNTIME.md` owns runtime behavior; `state/meta.json` and `state/scene.json` own hot campaign state.

## Runtime modules

This file is the navigation index for `politics` rules. Load only the module required by the causal action; the modules below are authoritative for their listed sections.

- `rules/politics/authority-law.md`: Authority and ownership; Offices, titles, and claims; Recognition, political support, and faction coalitions; Territory and occupation; Occupation, administration, resistance, and control; Law and justice; Legal cases, investigation, judgment, and enforcement; Fiscal and recruitment authority; military-appointment-authority; evidence-objective-fact-and-judgment-separation
- `rules/politics/factions-war.md`: Faction decision procedure; Small-faction and irregular ecology; Faction resources, internal approval, and implementation; War goals; Rebellions, invasions, sieges, and strategic event lifecycle; War capacity and exhaustion; Peace and negotiation; Mass mobilization, claims, and coercive consequences; automatic regional and global arcs; executable faction action gate
- `rules/politics/intrigue-governance.md`: Schemes, intrigue progress, and discovery; Vassals and delegated rulers; Surrender and prisoner policy; evidence-and-judgment; executable scheme and legal settlement; registered-institution-and-legal-clocks
