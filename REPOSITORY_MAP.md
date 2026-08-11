# Repository Map

This root guide is a concise compatibility/on-ramp map. The Game Master Skill has the detailed development map at `plugins/sword-and-banners/skills/sword-and-banners-game-master/references/repository-map.md`.

- `runtime/sword_runtime/`: deterministic execution, semantic commands, transactions/WAL/Git, causal simulation, production service, OAuth MCP, and Railway bootstrap.
- `runtime/sword_runtime/service_runtime.py`: hosted runtime wiring with fail-closed remote Git durability and non-probing contested preview readiness.
- `runtime/sword_runtime/api/operations.py`: bounded player-facing reads and semantic operations.
- `runtime/contracts/repository-map.json`: current machine authority/retrieval map. Retired routers are archived.
- `game/data/`: Sword setting, world, economy, formations/doctrine references, institutions, Houses, and historical background.
- `game/rules/`: current gameplay rules. Rules describe what is true now, not release history.
- `game/schemas/`: registered JSON schemas.
- `state/meta.json`: campaign identity, revision, world time, and player identity.
- `state/player.json`: Tang Wei's player record.
- `state/scene.json`: current player-facing scene projection.
- `state/runtime.json`: causal-host queue and zero-global-scan instrumentation.
- `state/index/owner-index-gold.json`: direct mutable-owner lookup.
- `state/forces/`: conserved manpower ownership.
- `state/formations/`: operational organizations. Formations do not redefine administrative ownership.
- `state/population/`, `state/states/`, `state/depots/`, `state/mounts/`: conserved state-scale authorities.
- `state/houses/`, `state/institutions/`, `state/factions/`: bounded autonomous actors.
- `state/fortifications/`, `state/sieges/`, `state/territory/`: exact warfare/territorial state.
- `state/information/`: claims and lawful knowers.
- `state/history/events/`: material semantic history.
- `plugins/sword-and-banners/skills/sword-and-banners-game-master/`: ChatGPT Game Master operating and narration Skill.
- `tests/runtime/`: architecture, transaction, hostile-input, long-horizon, acceptance, semantic-surface, and warfare tests.
- `tools/`: Gold audits, migrations, soak gates, and development utilities.
- `archive/legacy-execution/`: non-authoritative pre-Gold execution/reference data.

Do not recreate `game/data/runtime/`. That retired execution path is intentionally absent.
