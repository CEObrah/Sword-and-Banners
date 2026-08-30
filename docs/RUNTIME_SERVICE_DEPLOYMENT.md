# Sword & Banners Runtime Service Deployment

This is the canonical production setup guide for Railway, Auth0, and the ChatGPT Sword & Banners Runtime app. Keep tokens, secrets, private subject identifiers, and credentials out of Git, screenshots, and chat.

## Railway service

Deploy `CEObrah/Sword-and-Banners` from `main` only after the applicable local verification is green and the required GitHub Actions checks have passed on the branch/PR. Use `python tools/run_release_suite.py` for deliberate full releases or systemic changes that warrant campaign-wide verification; do not substitute CI for that deeper gate. A green GitHub check permits merge but is not proof Railway has deployed. Attach a persistent volume at `/data` for the campaign Git checkout plus private WAL/receipt/recovery data.

Set the non-secret/path configuration appropriate to the service:

```text
SWORD_CAMPAIGN_ROOT=/data/campaign
SWORD_RUNTIME_ROOT=/data/runtime
SWORD_GIT_URL=https://github.com/CEObrah/Sword-and-Banners.git
SWORD_GIT_REMOTE=origin
SWORD_GIT_BRANCH=main
RAILPACK_DEPLOY_APT_PACKAGES=git
```

Set `SWORD_GIT_TOKEN` privately in Railway. Use a fine-grained token restricted to this repository with only the repository access required for runtime fetch/push durability. Never commit or paste the token into ChatGPT.

`railway.toml` is the sole config-as-code file. It deploys on every non-`state/**` repository change and ignores state-only gameplay commits. This is required because the persistent checkout must stay synchronized with `main` for remote-durability preflight, while runtime-generated gameplay commits must not cause deployment loops.

The transaction preflight may also fast-forward a pristine live checkout when GitHub `main` is a strict descendant and the complete changed-path set is confined to the explicit runtime-neutral allowlist: GM Skill sources, docs, tests, tools, or the root README. It must never live-adopt `state/**`, runtime code, game/rule data, dependencies, deployment files, or unknown paths. Those continue to require normal deployment or deliberate repair. This prevents a harmless Skill/doc commit from freezing the next gameplay save without weakening campaign-history safety.

The production start command is:

```text
PYTHONPATH=/app/runtime python -m sword_runtime.bootstrap
```

Health endpoint: `/health`.

## Public domain and MCP resource

Generate one Railway HTTPS domain. The MCP resource is:

```text
https://<sword-domain>/mcp
```

Use that exact resource consistently as the MCP public URL and OAuth audience/resource.

## Auth0 API and permissions

Create a dedicated Sword API/resource server. Use the Sword MCP resource URL as the audience. Configure RS256 and permissions:

```text
sword:read
sword:write
```

Configure the ChatGPT Sword OAuth client for Authorization Code + PKCE as a public client and grant the user-delegated API permissions required by the connected app. Add the exact ChatGPT callback URL shown by the app connection.

## Sword MCP OAuth variables

Set privately on Railway:

```text
SWORD_MCP_PUBLIC_URL=https://<sword-domain>/mcp
SWORD_OAUTH_ISSUER_URL=https://<auth0-tenant>/
SWORD_OAUTH_JWKS_URL=https://<auth0-tenant>/.well-known/jwks.json
SWORD_OAUTH_AUDIENCE=https://<sword-domain>/mcp
SWORD_OAUTH_ALLOWED_SUBJECTS=<private Auth0 user subject>
SWORD_OAUTH_READ_SCOPE=sword:read
SWORD_OAUTH_WRITE_SCOPE=sword:write
SWORD_MCP_PREVIEW_SECRET=<private random base64url secret>
```

Optional/default settings:

```text
SWORD_OAUTH_ALGORITHMS=RS256
SWORD_OAUTH_ALLOWED_CLIENT_IDS=
SWORD_MCP_ALLOWED_ORIGINS=https://chatgpt.com,https://chat.openai.com
```

Never expose the preview secret, Git token, or private subject allowlist.

## Protected resource and health verification

Verify before live writes:

```text
https://<sword-domain>/health
https://<sword-domain>/.well-known/oauth-protected-resource/mcp
```

Protected-resource metadata should advertise the Sword MCP resource, Auth0 authorization server, and read/write scopes.

## ChatGPT Runtime app

Connect a custom MCP app to:

```text
https://<sword-domain>/mcp
```

Expected production tools:

- `get_play_context`
- `get_person_sheet`
- `inspect_game_object`
- `search_world_reference`
- `preview_command`
- `execute_command`
- `ooc_audit`

`search_world_reference` is a bounded cold-reference lookup. It may return exact static refs such as a known location identifier, but its results never prove current mutable state, occupancy, wounds, stock, control, private knowledge, relationships, or future outcomes.

Read tools require read access. Persistent execution requires write access.

After adding, removing, or changing an MCP tool or schema, deployment alone is not sufficient proof that ChatGPT sees the new surface. Refresh/review or recreate/republish the custom ChatGPT app action snapshot as required by the workspace plan, reconnect if necessary, and verify the currently discovered tool schema before consequential play.

## Game Master Skill and Project

Install the complete validated directory:

`plugins/sword-and-banners/skill/sword-and-banners-game-master/`

Use `assets/project-instructions.md` for the dedicated ChatGPT Project instructions. A GitHub Skill commit does not automatically update the ChatGPT-installed Skill. Verify the installed copy before claiming it is synchronized.

## Read-only initialization test

With the Runtime app selected, initialize the Project read-only. Require fresh `get_play_context` and verify player identity, location, world time, immediate situation, known obligations, and current decision state without mutation.

Then test one permitted person read, one permitted object read, and one bounded cold-reference lookup. Guessed/hidden mutable identifiers must fail closed and hidden information must not appear in player context.

## First persistent integration test

Use the player's next genuine in-world action, not a fabricated mutation. The required path is:

```text
fresh context
-> one current semantic command
-> preview
-> exact previewed command + attestation
-> execute
-> committed/duplicate receipt
-> fresh context
-> narration
```

Verify the resulting state commit reaches GitHub `main`. Verify the state-only gameplay commit does not trigger a Railway redeploy.

For battle, personal combat, and siege assault, preview must not reveal the contested outcome. Never retry previews to probe randomness.

## Recovery and repository-history changes

Do not wipe the persistent volume when bootstrap detects divergence. Preserve it and diagnose first. Safe history replacement may rehome a clean volume checkout only when committed campaign authority is identical; differing campaign truth must fail closed for deliberate repair.

## Ongoing development

Live play is continuous integration and playtesting. The Skill may surface worthwhile source improvements, but ordinary IC/OOC play must not silently edit GitHub or campaign truth. Explicit `OOC DEV:` work should inspect current source, implement the smallest coherent reusable fix, run the fast syntax/JSON/schema gate plus changed-path tests locally, push an isolated branch/PR, and inspect the required GitHub Actions clean-checkout gate. Red means diagnose and repair the correct implementation/test/fixture/environment/workflow owner; green permits merge. After merge, verify Railway deployment/source-head sync and the smallest safe live smoke path before resuming play. Keep any campaign repair separate from source changes. Deeper replay/soak diagnostics are selected only when the changed subsystem warrants them.

Run mutating tests and soak gates only on disposable copies, never on the authoritative live campaign root. Keep evolving-campaign tests snapshot-relative unless a value is intentionally immutable.