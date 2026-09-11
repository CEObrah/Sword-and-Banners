# Historical campaign rebaseline record - 2026-09-02

This document is **migration provenance**, not current deployment guidance.

On 2026-09-02 the repaired world snapshot was intentionally established as a new revision-1 baseline. The prior revision-51 snapshot is retained as forensic evidence at `docs/forensics/campaign-state-revision-51-pre-rebaseline.tar.gz`. The machine-readable record is `docs/CAMPAIGN_REBASELINE_20260902.json`.

The migration preserved authoritative hard-world state and cleared development-era presentation residue and old private recovery lineage as described by the manifest. That one-time decision does not make revision 1 a permanent live-state shape.

Current gameplay may advance to any later revision. `state/meta.json` is the sole authority for the mutable current revision and world time. Tests may verify that the rebaseline record remains internally consistent, but must not require the current save to equal revision 1 or the historical migration timestamp.

Ordinary deployments must follow `docs/RUNTIME_SERVICE_DEPLOYMENT.md` and preserve the current campaign/recovery volumes. The historical instruction to start the 2026-09-02 baseline on fresh storage applied only to that migration event.
