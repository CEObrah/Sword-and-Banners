# Sword and Banners

Persistent deterministic Warring States RPG operated through ChatGPT and the Sword runtime.

The canonical ChatGPT game-master operating package lives under:

`plugins/sword-and-banners/skills/sword-and-banners-game-master/`

Use these Skill sources for ChatGPT-facing behavior:

- `SKILL.md` for live-turn procedure, runtime use, agency, decision handoff, and GM orchestration;
- `references/narration.md` for voice and prose;
- `references/combat-and-warfare.md` for personal combat, formations, battles, and sieges;
- `references/player-interface.md` for natural-language controls and player-facing runtime use;
- `references/world-simulation.md` for living-world/autonomy principles;
- `references/live-play-review.md` for continuous playtest and improvement review;
- `references/runtime-architecture.md` for engine/service architecture;
- `references/repository-map.md` for source navigation and authority;
- `references/ooc-dev.md` for maintenance, testing, repair, Skill, and release procedure.

Repository authority remains separate:

- `runtime/` contains executable engine/service code;
- `game/` contains static mechanics, schemas, rules, and world data;
- `state/` contains mutable committed campaign truth;
- `runtime/contracts/repository-map.json` is the machine retrieval map;
- `.github/workflows/release.yml` runs the current smoke gate and manual full release verification;
- `railway.toml` is the sole Railway config-as-code file.

Production Railway/Auth0/ChatGPT MCP setup lives in `docs/RUNTIME_SERVICE_DEPLOYMENT.md`.

`README.md`, Skill prose, tests, examples, and chat history are never mutable campaign truth.
