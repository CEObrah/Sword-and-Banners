# Live Play Review

Treat real campaign play as the strongest integration test for Sword & Banners. Watch continuously for correctness, clarity, depth, balance, and player experience without turning every scene into a QA report.

## What to watch

### Runtime and mechanical correctness

Watch for:
- illegal battle or siege state;
- wrong commander custody or authority;
- formations acting despite unavailable personnel, mounts, equipment, supply, or location;
- conservation failures;
- impossible chronology;
- territorial changes without causal support;
- population or recruitment inconsistencies;
- stale readiness projections;
- duplicate or contradictory ownership;
- a semantic command accepting caller-controlled outcomes it should own;
- autonomous actors failing to progress or acting outside authority.

### Warfare quality

Watch for:
- one dominant tactical loop that makes other choices meaningless;
- unreadable formation geometry;
- battles that ignore command delay, terrain, morale, logistics, or reserves when those systems should matter;
- sieges resolving as generic battles without siege causality;
- casualty or recovery behavior that makes warfare consequence-free or impossibly punishing;
- formations failing to integrate replacements;
- unclear distinction among force ownership, command authority, assignment, and custody.

### Politics and House simulation

Watch for:
- offices granting powers they should not grant;
- House status being treated as state office;
- institutions acting without authority or resources;
- NPCs becoming passive until Wei interacts with them;
- Houses or states lacking credible responses to threats and opportunities;
- political consequences propagating instantly or not at all;
- family and succession systems behaving like detached ledgers rather than causal institutions.

### Economy and logistics

Watch for:
- money or resources being created or destroyed without a supported source;
- prices, wages, contracts, or recruitment becoming obviously dominant or nonsensical;
- armies moving or fighting without material support the rules say they need;
- duplicate treasury authority;
- logistics existing in data but never affecting play;
- economic systems blocking play through opaque requirements the interface does not explain.

### Information and knowledge

Watch for:
- the GM revealing hidden state;
- reports lacking provenance;
- enemy information becoming exact without observation;
- important known facts failing to appear in play context;
- stale or contradictory player-facing projections;
- recognition occurring without a lawful basis.

### Narration and UX

Watch for:
- state dumps instead of scenes;
- repeated summaries;
- NPC dialogue that sounds like schema fields;
- unclear speakers;
- menus before the player-declared action is resolved;
- fake or redundant choices;
- failure to provide decision scaffolding at a real unresolved decision;
- combat narration that hides geometry or causal result;
- battle narration that becomes an omniscient history-book summary;
- excessive backend terminology;
- important numbers omitted when the player needs them;
- trivial numbers overexposed when they do not matter.

## Severity

Flag an issue immediately when it:
- blocks the player's declared action;
- creates or risks false campaign truth;
- violates protected player agency;
- exposes hidden knowledge;
- makes a consequential decision materially misleading;
- creates a serious exploit, especially stochastic preview probing or ownership bypass;
- threatens transaction durability.

For smaller presentation or design issues, preserve IC flow. Surface the strongest finding at a natural stopping point rather than interrupting every scene.

## Diagnose before fixing

Classify the likely owner:

**GM Skill**: narration, dialogue, pacing, cast clarity, choice framing, battle presentation.

**Runtime interface**: command descriptions, payload discoverability, bounded reads, play-context projection, confusing failure responses.

**Runtime/rules mechanics**: resolution, timing, costs, combat, battle, siege, conservation, progression, recruitment, autonomy, economy, balance.

**Game data/rules**: world definitions, locations, Houses, equipment, prices, doctrine, historical background.

**Projection bug**: player-facing state disagrees with authoritative source. Diagnose the source before repair.

**Campaign truth defect**: committed state itself is wrong. Repair explicitly with migration/provenance, never by casual JSON edit.

**Feature opportunity**: repeated player intent has no supported semantic representation. That is not automatically a bug.

## Evidence standard

Base recommendations on one or more of:
- observed live play;
- current runtime output;
- bounded OOC audit;
- current source inspection;
- reproducible tests;
- repeated player friction.

Repeated symptoms carry more weight than one unusual outcome.

Do not propose a sweeping rebuild when a narrow reusable fix solves the actual problem.

## Sword-specific review checklist

When relevant, explicitly consider:
- commander custody;
- formation assignment and lifecycle;
- force and population conservation;
- battle legality;
- personal combat legality;
- siege causality;
- fortification state;
- territorial consequences;
- supply and resupply;
- replacement integration;
- House authority and treasury;
- career and office effects;
- state and House autonomy;
- mercenary contracts and initiative;
- institution capacity;
- family and dynasty causality;
- relationship and reputation propagation;
- information delivery and delay;
- market/economic balance;
- travel and route timing;
- command UX;
- NPC dialogue;
- choice quality;
- warfare narration.

## Development boundary

Ordinary IC and OOC play may identify and recommend improvements. It must not silently edit source or campaign truth.

When the player explicitly asks to fix or improve the game, switch to `OOC DEV:` procedure, inspect current source, implement the smallest coherent reusable change, run the appropriate Gold gates, and keep campaign repair separate from code changes.
