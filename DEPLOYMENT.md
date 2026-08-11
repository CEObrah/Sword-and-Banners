# Sword & Banners Production Deployment

This guide prepares the persistent Sword runtime for Railway, Auth0, and a ChatGPT custom MCP app. Keep every token, secret, and private subject value out of Git.

## 1. Railway service and persistent volume

Deploy this private GitHub repository as a Railway service from `main` after the Gold release gate is green.

Attach a persistent volume with enough space for the Git checkout, WAL, receipts, and long-running campaign history. Mount it at `/data`.

Set these Railway variables:

```text
SWORD_CAMPAIGN_ROOT=/data/campaign
SWORD_RUNTIME_ROOT=/data/runtime
SWORD_GIT_URL=https://github.com/CEObrah/Sword-and-Banners.git
SWORD_GIT_REMOTE=origin
SWORD_GIT_BRANCH=main
SWORD_GIT_TOKEN=<private fine-grained GitHub PAT>
RAILPACK_DEPLOY_APT_PACKAGES=git
```

The GitHub PAT should be fine-grained, restricted to this repository, with repository Contents read/write permission only as needed for runtime commits and pushes.

Railway's GitHub deployment connection and `SWORD_GIT_TOKEN` are different things. The deployment connection watches source. The runtime token lets the live campaign checkout fetch, commit, push, and verify gameplay state.

The service starts through `railway.toml`:

```text
PYTHONPATH=/app/runtime python -m sword_runtime.bootstrap
```

Health check:

```text
/health
```

Gameplay commits under `state/**` are intentionally excluded from deployment watch patterns. Source or game-definition changes trigger a deployment; state-only gameplay commits do not.

## 2. Generate a public Railway domain

After the service boots with its base Git variables, generate a Railway HTTPS domain.

Use that domain consistently below. If the public service is:

```text
https://sword-example.up.railway.app
```

then the MCP resource URL is:

```text
https://sword-example.up.railway.app/mcp
```

Do not configure OAuth with one domain and later connect ChatGPT to another without updating the audience/resource values.

## 3. Create a separate Auth0 API for Sword

Use a separate Auth0 API/resource server for Sword rather than reusing Shinobi's audience.

Recommended API identifier/audience:

```text
https://<sword-railway-domain>/mcp
```

Signing algorithm:

```text
RS256
```

Create permissions:

```text
sword:read
sword:write
```

Enable User-Delegated Access for the ChatGPT Sword OAuth application and grant both permissions.

Enable Allow Offline Access for the API if the Auth0 tenant/app flow requires refresh/offline access.

In the Auth0 tenant advanced OAuth settings, enable the Resource Parameter Compatibility Profile so RFC 8707 `resource` requests from ChatGPT are accepted.

## 4. Create the ChatGPT Sword OAuth client in Auth0

Create a dedicated public/native OAuth application for Sword.

Use:
- public/native client behavior;
- PKCE S256;
- token endpoint authentication method `none`;
- Authorization Code flow appropriate for a user-delegated ChatGPT connection.

Do not reuse the Shinobi client ID or client secret configuration.

The exact ChatGPT callback URL is generated when the custom App connection is created. Add that exact callback URL to the Auth0 application once ChatGPT shows it, then reconnect or reauthorize the App.

## 5. Set Sword MCP OAuth variables on Railway

After the Railway domain and Auth0 API exist, set:

```text
SWORD_MCP_PUBLIC_URL=https://<sword-railway-domain>/mcp
SWORD_OAUTH_ISSUER_URL=https://<auth0-tenant>/
SWORD_OAUTH_JWKS_URL=https://<auth0-tenant>/.well-known/jwks.json
SWORD_OAUTH_AUDIENCE=https://<sword-railway-domain>/mcp
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

`SWORD_MCP_PREVIEW_SECRET` must be a private random base64url value at least 43 characters long. Never paste it into ChatGPT, commit it, or expose it in screenshots.

`SWORD_OAUTH_ALLOWED_SUBJECTS` is an allowlist for the Auth0 user subject permitted to operate this private campaign. Keep the actual value private.

## 6. Verify the protected resource metadata

After Railway redeploys, verify this public endpoint:

```text
https://<sword-railway-domain>/.well-known/oauth-protected-resource/mcp
```

It should advertise the Sword MCP resource URL, the Auth0 authorization server, and both scopes:

```text
sword:read
sword:write
```

Also verify:

```text
https://<sword-railway-domain>/health
```

returns healthy status.

Do not proceed to live campaign writes if bootstrap, health, or protected-resource metadata fails.

## 7. Create the ChatGPT custom App

In ChatGPT developer mode, create a custom MCP App pointing to:

```text
https://<sword-railway-domain>/mcp
```

Use the dedicated Sword Auth0 user-defined OAuth client.

After ChatGPT provides its callback URL:
1. add the callback URL to the Sword Auth0 application;
2. ensure the Auth0 API has both `sword:read` and `sword:write` user-delegated permissions for that application;
3. reconnect or reauthorize the ChatGPT App.

Expected discovered tools:
- `get_play_context`
- `get_person_sheet`
- `inspect_game_object`
- `preview_command`
- `execute_command`
- `ooc_audit`

Expected scope behavior:
- read tools require `sword:read`;
- `execute_command` requires `sword:read` and `sword:write`.

## 8. Install the Sword & Banners Game Master Skill

Package/install the complete directory:

```text
plugins/sword-and-banners/skills/sword-and-banners-game-master/
```

The package must include `SKILL.md`, `agents/openai.yaml`, all reference files, and the Project-instructions asset.

After any Skill update, replace the installed Skill with the newly validated package.

## 9. Create the dedicated ChatGPT Project

Copy the contents of:

```text
plugins/sword-and-banners/skills/sword-and-banners-game-master/assets/project-instructions.md
```

into the dedicated Sword & Banners Project instructions.

The Project should use:
- the installed Sword & Banners Game Master Skill;
- the connected Sword & Banners Runtime App.

Conversation memory is continuity only. Runtime state remains the save game.

## 10. Read-only initialization test

In the new Project, with Sword & Banners Runtime selected, send:

```text
OOC: Initialize this Project as my live persistent Sword & Banners campaign.
Use the installed Sword & Banners Game Master Skill and the Sword & Banners Runtime.
Retrieve the current authoritative play context and tell me briefly:
1. who I am playing,
2. where I am,
3. current world time,
4. immediate situation,
5. known upcoming obligations / decision points.
Do not mutate campaign state or advance time.
```

The response must come from fresh `get_play_context`, not chat memory.

If the Runtime App is selected but tools fail to surface transiently, the Skill retries exactly once. If they remain unavailable, it fails closed and asks for selection/reconnection/reauthorization rather than inventing state.

## 11. Bounded read tests

From fresh context:
- read Tang Wei's permitted person sheet;
- inspect one exact permitted formation/object ref;
- confirm guessed hidden IDs fail closed;
- confirm hidden information does not appear in player context.

## 12. Preview/execute integration test

For the first real persistent action:
1. obtain fresh context;
2. select one current semantic command from the returned command catalog;
3. preview it at the exact revision;
4. confirm a complete command and short-lived attestation are returned;
5. execute that exact command and attestation;
6. confirm a committed receipt;
7. refresh play context;
8. verify GitHub `main` contains the runtime-generated state commit;
9. verify Railway did not redeploy merely because `state/**` changed.

Do not use a fabricated test action that changes campaign truth unnecessarily. Prefer the player's next genuine action in the current scene.

## 13. Contested action security test

When a real battle, personal-combat action, or siege assault eventually occurs, verify that preview returns readiness without the contested result.

Do not repeat preview to probe randomness. The outcome should be generated once during execution and only narrated after the committed receipt.

## 14. Ongoing live-play development

Normal IC/OOC play may identify concrete quality problems and improvement opportunities through the Skill's live-play review rules.

Source changes require explicit OOC DEV work. Campaign truth defects require explicit repair/migration. After meaningful runtime/game source changes, pass the Gold release gate before treating the new code as production-ready.
