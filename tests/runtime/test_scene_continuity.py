import json

from fastapi.testclient import TestClient


def test_stale_scene_retains_only_presentation_continuity(campaign):
    from sword_runtime.api.app import create_app

    token = "c" * 48
    headers = {"Authorization": f"Bearer {token}"}
    scene_path = campaign / "state/scene.json"

    with TestClient(create_app(campaign, token)) as client:
        projected = client.get("/v1/play/context", headers=headers).json()
        assert projected["scene"]["projection_status"] == "fresh_runtime_projection"
        assert projected["scene"]["continuity_anchor"]["presentation_only"] is True
        baseline_reports = projected["scene"]["available_reports"]

    scene = json.load(open(scene_path))
    prior_summary = "A prior authored scene summary used only as presentation continuity."
    scene["scene_summary"] = prior_summary
    scene.setdefault("narrative", {})["last_scene_summary"] = prior_summary
    scene["world_time"] = "stale-continuity-test"
    scene_path.write_text(json.dumps(scene, indent=2) + "\n")

    # A fresh service instance must never present the stale authored scene as
    # current truth. It rebuilds a current runtime projection and carries only
    # the old prose summary as an explicitly presentation-only anchor.
    with TestClient(create_app(campaign, token)) as client:
        refreshed = client.get("/v1/play/context", headers=headers).json()
        assert refreshed["scene"]["projection_status"] == "fresh_runtime_projection"
        anchor = refreshed["scene"]["continuity_anchor"]
        assert anchor["presentation_only"] is True
        assert anchor["summary"] == prior_summary
        assert "does not prove current presence" in anchor["warning"]

        assert refreshed["scene"]["unresolved_decision"] is None
        assert refreshed["scene"]["observable_pressures"] == []
        assert refreshed["scene"]["active_questions"] == []
        assert refreshed["scene"]["available_reports"] == baseline_reports
        assert refreshed["scene"]["unresolved_hooks"] == []
