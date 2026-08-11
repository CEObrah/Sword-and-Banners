# Repository Map

- `runtime/sword_runtime/`: deterministic execution, transaction/WAL/Git, causal simulation, service/API/MCP and Railway bootstrap.
- `runtime/contracts/`: current authority map only. Retired routers are archived.
- `game/data/`: Sword setting, world, economy, formations/doctrine references, institutions and canon background.
- `game/rules/`: current gameplay rules. Rules describe what is true now, not release history.
- `game/schemas/`: registered JSON schemas.
- `state/runtime.json`: causal-host queue and zero-global-scan instrumentation.
- `state/index/owner-index-gold.json`: direct mutable-owner lookup.
- `state/forces/`: conserved manpower ownership.
- `state/formations/`: operational organizations. Formations do not redefine administrative ownership.
- `state/population/`, `state/states/`, `state/depots/`, `state/mounts/`: conserved state-scale authorities.
- `state/houses/`, `state/institutions/`, `state/factions/`: bounded autonomous actors.
- `state/fortifications/`, `state/sieges/`, `state/territory/`: exact warfare/territorial state.
- `state/information/`: claims and lawful knowers.
- `state/history/events/`: material semantic history.
- `archive/legacy-execution/`: non-authoritative pre-Gold execution/reference data.
