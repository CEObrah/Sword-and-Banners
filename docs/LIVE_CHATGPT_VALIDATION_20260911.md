# Sword live ChatGPT handoff — 11 September 2026

This is the first bounded repair candidate following [the architecture audit](AI_GM_ARCHITECTURE_AUDIT_20260911.md). Local checks exercise transactions and the actual MCP SDK, but do not certify the installed ChatGPT Skill, remote OAuth, Railway routing, NPC quality or sustained gameplay. Run this short live check before further architectural changes.

## Matching artifacts and identity

The delivered source archive is `sword-and-banners-runtime.zip`; the separately installable archive is `sword-and-banners-game-master.zip`. Both come from the same source tree. `RELEASE_MANIFEST.json` in the source archive records every packaged file hash, runtime/MCP/schema/Skill/dependency identities, the original Git commit, whether it includes uncommitted edits, and the supplied campaign baseline. A separate `ARTIFACT_CHECKSUMS.json` identifies the ZIP bytes.

Expected `release_contract_sha256` for this candidate:

```text
ec08f177e28c26a5971b57e0697a219231313bcff2aee5f55fd8f620cdee5063
```

The same value is printed as `GM_SKILL_CONTRACT_TOKEN` in the installed Skill. It is a non-secret compatibility identifier. Do not replace a stale Skill's token with a value copied from a server error; install the matching Skill files.

The archive includes the existing supplied save:

| Identity | Supplied value |
| --- | --- |
| Campaign | `sword-banner-tang-wei-main` |
| Baseline | `sanyou-campaign-handoff-r45-20260908` |
| Snapshot revision | 45 |
| Snapshot world time | `244-BCE-12-21T12:00:01+08:00` |

Live play may already have advanced beyond this snapshot. Read its actual revision, time, location and health. A new chat resumes the configured campaign. **This candidate does not create a fresh campaign.** The new identity guards reject an unintended campaign/baseline; they do not manufacture a clean seed. Isolated fresh-campaign creation remains a later repair.

## Deploy and install

1. Review the source changes and deploy their exact runtime, game/schema, dependency and Skill files through the existing source-to-Railway path. This handoff has not pushed a commit or deployed Railway. The original commit alone does not identify the candidate: the source manifest explicitly records uncommitted edits. A later deployment commit may differ while its content fingerprint matches.
2. Keep the existing campaign and private recovery volumes. Keep the baseline ID unchanged for this resume test. Do not copy the archived `state/` over a progressed live save. Follow [the existing deployment runbook](RUNTIME_SERVICE_DEPLOYMENT.md), including `PYTHONPATH=/app/runtime python -m sword_runtime.branch_bootstrap`. Bootstrap reconciles source with the baseline-scoped campaign branch.
3. Confirm production exposes a valid `RAILWAY_GIT_COMMIT_SHA` and the pinned dependencies. Missing/invalid production image identity and dependency drift now fail closed. These conditions require fixing deployment; they are not reasons to reset the campaign.
4. Replace the installed GM Skill with `sword-and-banners-game-master.zip`. Apply its `assets/project-instructions.md` to the existing game Project as appropriate. Refresh the connected MCP tool definitions after the server deployment; `preview_command` now accepts the Skill token and expected campaign ID. See the [official ChatGPT connector deployment guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).
5. Start a new ordinary chat in that Project for the following resume test. Existing unexecuted preview tokens from an earlier release must be previewed again. Already-committed exact retries can recover their receipt without a current preview token.

## Test 1 — establish the live chain before playing

Paste this into ChatGPT:

> OOC release check. Load the installed Sword GM Skill and call get_play_context using its own printed skill_contract_token, expected_campaign_id `sword-banner-tang-wei-main`, and expected_baseline_id `sanyou-campaign-handoff-r45-20260908`. Do not mutate state yet. Report campaign ID, baseline, actual revision/world time, player location/health, active scene/combat or pending decision, release_contract_sha256, runtime_source_sha256, mcp_contract_sha256, state_schema_sha256, gm_skill_sha256, runtime_dependencies, image_source_commit, campaign_checkout_commit, source_tracking_commit, deployment_id and deployment_compatible. Compare the release contract with the handoff. If anything disagrees, stop the gameplay test and show the exact error.

Pass: the combined hash matches above, component hashes match the manifest, dependency mismatches are empty, production deployment is compatible with a nonempty image commit, and the campaign identity/baseline match the intended save. The live revision is read from the server; it is not assumed to equal 45. Unknown deployment identity in a local process is explicitly not proof of a live deployment.

If this step fails, return the diagnostic first. Do not spend gameplay turns working around a stale runtime or Skill.

## Test 2 — meaningful AI-authored memory, with no invented hard event

Paste:

> Resume from the authoritative current scene. For this short integration check, use an established NPC who is actually present and able to converse. If none is eligible, report the missing precondition instead of inventing presence or advancing time just to satisfy the test. I want a natural conversation that can meaningfully affect the NPC's interpretation of Wei. I say: “When a report is uncertain, I would rather you tell me what you doubt than give me an answer merely because I outrank you.” Let the NPC reason and respond from their own history and personality. Choose a plausible important interpretation or intention if this warrants one, persist it through npc_cognition with actual witnessed scene evidence, and continue the scene. Do not create a missing shipment, change loyalty points, issue an order, or decide Wei's thoughts from this speech.

Then play two ordinary conversational beats in your own words. The dialogue should show a distinct NPC response and some initiative. There is no predetermined correct emotion or promise. If this exchange would not plausibly matter, the GM should explain that in the OOC result; the cognition check is then inconclusive, rather than a reason to manufacture drama.

Request this separate diagnostic after the scene beat:

> OOC checkpoint A. Report the command types, request IDs, revision before/after each committed command, and whether meaningful NPC cognition was accepted. In this OOC diagnostic only, identify its subject_ref, cognition_ref, statement, epistemic_status, reason and basis_refs. Verify that its evidence really occurred and the NPC witnessed it. Report hard-state/time changes separately. Do not let this diagnostic become Wei's in-character knowledge.

Pass: when important cognition is chosen, speech/fact evidence and the cognition have committed receipts. The cognition is an attributed belief/intention/interpretation/recollection, with a reason; it does not assert objective truth or alter time, resources, injuries, scores or player knowledge. The NPC remains creatively portrayed. Record extra tool calls and awkward stalls as product failures even if the save is consistent.

## Test 3 — a genuinely separate conversation reads the same save

Create Chat B in the same Project without pasting Chat A's dialogue, cognitive statement or transcript. Paste:

> Continue this campaign. Load the Skill and fresh get_play_context with the campaign and baseline IDs from this handoff. Report the current revision/time/location briefly OOC, then continue the existing scene naturally. Let present NPCs act from their durable private cognition and relationships. If a compact entry is truncated, use the exact person sheet. Do not reconstruct earlier events from this prompt or reveal private motives as Wei's knowledge.

Then ask naturally about the earlier topic, without restating the desired answer. Pass: Chat B uses the committed state and recalls the relevant interpretation and its cause. The NPC may conceal, reinterpret or discuss it plausibly; verbatim repetition is not required. No time reset, resurrected wound, duplicated resource, invented prior dialogue or private-knowledge leak should appear.

Return checkpoint A and the Chat B response so a reviewer can distinguish durable retrieval from plausible improvisation.

## Test 4 — changed interpretation and exact retry

If Test 2 created an entry, continue the same eligible scene with a substantive clarification or new witnessed event. Ask the GM OOC to assess whether it should update or resolve that entry, preserving the stable cognition_ref and recording new causal evidence. An arbitrary change with no new evidence should be rejected. When it changes, the old version must be retrievable through `inspect_game_object(previous_history_ref)` while the NPC remains permitted. The current interpretation and its history stay private to the GM until disclosed in character.

For retry validation, use a successful cognition command from this test, or close the scene only when the scene has naturally finished. Paste:

> OOC idempotency check. Resubmit the exact already-committed command envelope once using the same request_id, revision and payload. Do not make a new request ID or change fields. Report whether execute_command returns status duplicate and the original committed_revision. Read fresh context to verify that this retry made no additional revision advance or second effect. If the original envelope is unavailable, mark this check unperformed rather than reconstructing it.

Pass: the original receipt is returned even if successful execution changed scene preconditions. A genuinely new action needs a new request ID; a modified envelope reusing an old ID must fail.

## Optional later checks

After the short chain above passes, use a deliberately isolated test campaign for dangerous creative combat, treatment and combined-arms orders. That isolation workflow has not been added in this pass. Do not claim combat or strategic AI is repaired on the strength of the social test. Useful live questions are whether unusual tactics survive interpretation, narration follows physical results, NPC generals reason independently, and bodies/troops/time/material remain conserved.

## Return bundle and stop point

Return both chat transcripts, visible tool calls/errors/receipts, the release-check output, checkpoint A, fresh revision readings, and your observations about NPC initiative, repetition, pacing and knowledge leaks. Include a bounded `ooc_audit` for any failure, describing the expected versus observed result. Redact OAuth credentials and bearer tokens; request IDs and compatibility hashes are not secrets.

The next implementation pass should be driven by that evidence. Do not run a long simulated campaign or the entire local suite to substitute for this live check.
