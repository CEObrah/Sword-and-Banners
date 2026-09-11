# Sword first repair pass — 11 September 2026

The [pre-repair A–P audit](AI_GM_ARCHITECTURE_AUDIT_20260911.md) established the actual ChatGPT/Skill/MCP/runtime/persistence path before implementation. This pass addresses its first four priorities in Sword. Shinobi remains unchanged. There is no new client, mass refactor, long campaign simulation or claim of sustained live reliability.

## Changes and their practical effect

| Boundary | Repair | Result |
| --- | --- | --- |
| Context and planning | A thread-reentrant campaign lease uses the existing cross-process file lock. Complete most-derived public operations, shared-planner previews/executions, attested MCP context, reference search and extension reads acquire it. Outermost entry recovers any pending WAL, checks the repository and resets planner caches. | Concurrent operations cannot share half-reset planner state or read between file replacements. Existing per-command coordinator authority remains intact. |
| Retry identity | Authorization and immutable receipt lookup precede current scene/wake validation. New receipts bind the original public envelope while planning uses its validated translation. | A successful scene close can be retried after the scene has closed. Exact legacy scene/interaction translations are recovered without re-running changed preconditions. |
| Version proof | A normalized content fingerprint binds runtime Python, MCP/contracts, schemas, game content, dependency declarations, release lineage and the complete Skill. Context compares actual source files and installed dependency versions. | A stale/missing Skill token, unsynchronized build or dependency drift cannot obtain normal playable context. Preview requires the matching token and expected campaign ID; unexecuted preview attestations cannot cross releases. |
| Deployment/campaign identity | Context reports component hashes, image/check-out/tracking commits, deployment ID and baseline. Missing/invalid image SHA under production markers fails closed; local unknown identity is not reported as deployment proof. Expected campaign/baseline guards are available. | A new chat cannot silently satisfy a request for another campaign. Operators can compare the running process with the delivered manifest. This does not create a fresh campaign or prove external routing/ref freshness. |
| AI-authored durable meaning | `npc_cognition` exposes `gm_cognition_action` for create/update/resolve, with schemas, selective retention, causal evidence, version history and private retrieval. | The GM can persist an unexpected NPC suspicion, goal, grievance, plan, relationship interpretation or recollection without a named quest handler. The accepted fact is that the NPC holds this cognition. |
| Social context | Private NPC packets preserve existing relationship value/evidence/cause fields as well as authored cognition. | The GM receives reasons and history, not just static traits or a score. |
| Release artifacts | The deterministic source ZIP includes `RELEASE_MANIFEST.json`; the packager can also build and verify a matching installable Skill ZIP. | Source, Skill and deployment checks have comparable identities. Uncommitted source status is explicit. |

## Cognition authority and lifecycle

The new command accepts an exact established NPC in the active scene at the player's actual location. It cannot write the player's inner state. It requires 1–8 exact primary scene speech/fact refs, with access attributable to that NPC; newly recorded speech preserves the actual participant witness set at recording time. Legacy speech lacking that set proves only the speaker's access. Derived literary continuity is not primary evidence.

The GM supplies a short semantic kind, statement, epistemic status, salience and causal explanation. Runtime validates identity, evidence access, lifecycle, size and write scope; it cannot mechanically prove that the psychological interpretation is good. That judgment remains the AI GM's job and a live-test question. A plan is an intention, not an issued military order. A suspicion is not proof that its content happened. The command changes neither time nor physical person state, relationships/scores, information claims, resources or orders.

Current per-NPC owners contain at most **32 entries total, including resolved entries**. Compact context includes at most eight priority entries with a truncation marker; an exact person sheet returns all current entries. Updates/resolutions require new causal evidence. Prior versions live in separate immutable history files, linked through `previous_history_ref`, and can be read one at a time through `inspect_game_object` after rechecking the NPC's current person-sheet permission. Explicit private markers are removed by the generic player-facing REST transport.

Capacity currently fails explicitly instead of silently erasing or rewriting memory. There is no consolidation/archive lifecycle for freeing those 32 slots yet. Use this bridge selectively and report capacity pressure from live play. It is not a finished years-long cognition system.

## Targeted validation performed

Tests ran in an external disposable Python environment using the repository's exact service pins, including MCP **2.0.0**, plus pytest **8.4.2**. Production-operations tests used disposable Git campaigns. No test mutated the supplied campaign.

| Selected check | Evidence and result |
| --- | --- |
| Three isolation regressions | Deterministic thread interleavings exercise the actual operation wrapper and runtime preview: another thread stays excluded through nested calls, a complete derived read waits until both files are written, and simultaneous previews do not overwrite shared planner state. Passed. |
| Existing authorization and four transaction regressions | Duplicate actor authorization, normal duplicate/stale behavior, crash-after-apply rollback, crash-after-commit recovery and retry after precommit rollback. Passed. |
| Seven cognition/receipt regressions | Actual production preview/commit/reopen; private compact and exact-sheet retrieval; public redaction; unchanged hard-state files; stale revision and missing new cause; update/resolution history retrieval; rejected player thoughts, invented evidence, extra resource fields and objective-truth status; current and legacy close retries. Passed. |
| Real MCP HTTP/session regression | Actual `ClientSession`, serialized tool catalog, authenticated adapter middleware, context/token/campaign guards, contract enums, read-only preview, commit, duplicate and fresh context. Passed within a 25-second timeout. Only JWT verification was stubbed; external OAuth, network and ChatGPT were not tested. |
| Release/deployment identity checks | Source/schema/Skill/lineage edits change fingerprints; pinned dependency drift is identified; missing production identity fails; preview HMAC cannot cross releases; existing source-versus-state deployment checks. Passed. |
| Existing receipt/scene/packaging/delivery checks | Nested receipt JSON, scene speech/thread/fact lifecycle, source packaging inclusion/exclusion, release baseline, Skill synchronization and deployment lineage checks. Passed. |

The final new cognition/MCP/identity/deployment selection passed **19 tests in 27.37 seconds**. The earlier isolation/authorization/transaction selection passed **9 in 8.55 seconds**. The existing scene/receipt/packaging/delivery selection initially had **33 passes and one test-fixture failure**: it assumed the user's Git default branch was `master`. Its disposable repository now explicitly initializes `main`; the affected delivery file then passed **11 tests in 0.55 seconds**. No application behavior was relaxed to fix that test.

The old delivery test's source-substring assertions about MCP calls were removed in favor of the real protocol regression. Existing prose-policy tests remain instruction lint; they do not validate intelligence or narration. No full suite, broad changed-path runner, long replay, yearly simulation or AI evaluation was run.

The release packager additionally checks Python syntax, active JSON/schema validity, supplied release-state digest, and synchronized Skill identity against the extracted source archive, and byte-verifies both ZIPs. Artifact checksums accompany the handoff.

## Remaining limits and next decision

Transactions remain atomic per semantic command, not for a whole multi-command player turn. The new cognition operation generally adds one preview/execute pair plus a refresh, and primary evidence may need its own transaction. Batch design and live call-volume measurements are deferred.

Exact compatibility recovery for historical translated receipts covers scene and interaction envelopes. New writes consistently retain their original public envelope; other old translation families may still require a targeted migration if live evidence exposes one. The new lease serializes reads with writes, favoring coherent snapshots over concurrent read throughput; it is not a database snapshot system.

Generic relationship mutation can still accept inadequately established causes. Offscreen schemes, new named NPC creation, binding NPC promises, tactical/strategic intention handoffs, explicit fresh-campaign creation and broader time/body/material/troop invariant repairs remain deferred. Existing runtime strategic/combat choices were not replaced. The new bridge alone does not make the game fully AI-directed.

The source remains an uncommitted local candidate based on the original audited commit. No GitHub push, Railway deployment, remote OAuth check or installed Skill replacement was performed. The supplied Sword `state/` and the entire Shinobi checkout remain unchanged. Follow [the exact live ChatGPT guide](LIVE_CHATGPT_VALIDATION_20260911.md), then return the transcripts and release diagnostics before the next architectural pass.
