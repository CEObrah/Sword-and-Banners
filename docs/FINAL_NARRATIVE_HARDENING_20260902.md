# Final Narrative Hardening - 2026-09-02

## Observed live-play failure

The revision-1 package could still produce mechanically correct but narratively weak command scenes. The representative failure had this shape:

`dateline -> weather/accounting -> intelligence distinctions -> officers verbalize state semantics -> six-option command menu`

This is readable tactical briefing prose, but it fails the intended serialized historical-fiction experience. The problem was systemic rather than one bad sentence.

## Root causes

1. The GM Skill contained strong scene-first guidance, but the hardest anti-report rules were buried deep enough that a draft could satisfy them superficially.
2. The compact MCP writer handoff still carried too much report-shaped material, including historical staff/report detail and repeated static directing doctrine.
3. The choice guidance still normalized six visible options when fewer would preserve a stronger dramatic handoff.
4. Sword had a real characterization routing defect. The previous package contained 94 authored behavior-profile files, but `behavior-profile-index.json` registered only 43. Many authored recurring-character profiles therefore could not reach normal GM-private scene direction.
5. Fourteen recurring Tang Wei command people still had placeholder formation-derived display names and generic role cognition instead of usable recurring-character identities.

## Repairs

### Whole-game prose contract

The Sword & Banners GM Skill now has a top-level hard narrative quality gate. All player-facing material, including command, politics, household life, travel, training, personal combat, battles, sieges, recovery, and aftermath, is treated as a serialized lived saga rather than a turn report.

The Skill and scene-craft references explicitly reject polished state dumps, validator-shaped exposition, characters used as schema mouthpieces, premature decision screens, and resolver-transcript combat. Narrative selectivity is mandatory: the writer chooses the dramatic pressure and camera focus instead of emptying the context packet into prose.

Combat and warfare explicitly use dramatic sequencing around mechanically committed truth: anticipation, geometry, human intent expressed through action, attack/defense interplay, reversal, consequence, and aftermath. Repetitive exchanges are compressed; shape-changing moments expand.

### Choice UX

Choice scaffolding now uses the smallest useful set, usually two to four materially distinct courses. More than five is exceptional. A menu appears only after a genuine protected decision has matured; it is not the default ending of a council or briefing.

### Runtime writer handoff

`gm_scene_context.scene_direction` now exposes dynamic narrative-stage and paraphrase-risk signals without creating story outcomes.

The compact writer packet no longer carries natural-language summaries for world pressure or interaction handles. Historical upward-report rows and full directive prose are cold and available through exact operation inspection when they materially matter.

Long static director/selection/performance doctrine was removed from the per-turn compact packet because the GM Skill owns that stable procedure.

The measured live compact context for the current Sword baseline is 46,786 bytes, down from the 49,196-byte regression and below the maintained 48,000-byte ceiling without weakening the threshold.

### Characterization routing

`game/data/people/behavior-profile-index.json` now registers every authored behavior profile: 108 of 108.

Evidence-limited historical profiles are now preserved as GM-private role/anchor/dialogue constraints instead of disappearing merely because they do not have a freeform `behavior` object.

The immediate Tang Wei command cast now has real recurring identities and distinct authority-false behavior profiles. Examples include Luo Heng commanding Black Banner and Ma Cheng commanding Red Lance. Lin Zhen, Ren Qiao, Han Shou, Pei Rong, Deng Kai, and Lu Cheng also received differentiated professional voice/bias profiles instead of cloned generic military-report behavior.

Fourteen placeholder Tang command identities were corrected in the revision-1 baseline while preserving their exact owner IDs, command assignments, formations, conservation, and mechanical authority.

## Cross-game analogue audit

The shared narration, combat-presentation, choice, and report-handoff defect was audited and repaired in Shinobi as well.

Shinobi does not have Sword's behavior-profile-index architecture. Its scene direction derives character context from exact person owners, relationships, current goals/cognition, mission/process state, presence, and scene history. No analogous authored-profile indexing loss was found. Therefore the shared systemic fix is mirrored in both games, while the Sword-specific profile-index and placeholder-command-character repair remains local to Sword.

## Verification ledger

Final Sword tree:

- `python tools/quick_check.py`: PASS, 1,383 JSON files, 235 registered schemas.
- `PYTHONPATH=runtime python tools/validate_release.py`: PASS, 124/124 checks.
- Maintained `tools/test_changed.py` selected 21 modules. The aggregate process exceeded the execution window, so it is not counted as a pass or failure. The exact selected modules were then run in three maintained shards:
  - architecture / transactions / Skill / narrative: 50 passed;
  - scene / interaction / continuity: 69 passed;
  - military planning / conservation / logistics / progression: 41 passed.
  - Total across the exact selected modules: 160 passed.
- Additional final scene/narrative/continuity batch: 45 passed.
- Narrative hard-gate regression file: 7 passed, including cold-report-prose and characterization-index coverage.
- Current compact MCP context: 46,786 bytes.

## Release boundary

This package is revision-1 source plus baseline state for a clean `main` deployment. It does not claim that Railway, MCP connector state, or an installed ChatGPT Skill has already refreshed. Deployment should use wiped campaign and private recovery storage as previously specified for the revision-1 rebaseline.
