# Rules

These files are the live rule authorities for Sword and Banners. Only current canonical rules and structured registries are gameplay authority. Where a structured mechanics registry exists under `game/data/mechanics/`, the structured registry controls numerical resolution and the Markdown rule explains intent and usage.

`family.md` owns marriage, household, parentage/guardianship and succession lifecycle semantics; structured rules are in `game/data/mechanics/family.json`.
## Runtime parity

`game/data/mechanics/rules-runtime-parity.json` is the authoritative implementation-status map for these rule files. A rule may be normative authority without every paragraph being executable. Entries marked `live` map to production commands, runtime hooks, or causal hosts. Entries marked `mixed` name the executable scope and explicitly state what remains descriptive. Entries marked `descriptive` or `deferred` must not be presented by the runtime, narrator, tests, or release notes as implemented mechanics.

The current release validator fails if a rule file is missing from the parity map, if a `live`/`mixed` entry has no executable hook, or if a listed command/hook/host does not exist in the production runtime.

