import json

from fastapi.testclient import TestClient


def test_stale_scene_retains_only_presentation_continuity(campaign):
    from sword_runtime.api.app import create_app

    token = "c" * 48
    scene_path = campaign / "state/scene.json"
    with TestClient(create_app(campaign, token)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        fresh = client.get("/v1/play/context", headers=headers).json()
        assert fresh["scene"]["projection_status"] == "fresh"
        assert fresh["scene"]["continuity_anchor"] is None

        scene = json.load(open(scene_path))
        prior_summary = scene.get("scene_summary")
        if not isinstance(prior_summary, str) or not prior_summary.strip():
            prior_summary = scene.get("narrative", {}).get("last_scene_summary")
        assert isinstance(prior_summary, str) and prior_summary.strip()

        scene["world_time"] = "stale-continuity-test"
        scene_path.write_text(json.dumps(scene, indent=2) + "\n")

        stale = client.get("/v1/play/context", headers=headers).json()
        assert stale["scene"]["projection_status"] == "stale_after_state_change"
        anchor = stale["scene"]["continuity_anchor"]
        assert anchor["presentation_only"] is True
        assert anchor["summary"] == prior_summary.strip()
        assert "does not prove current presence" in anchor["warning"]

        # The anchor preserves orientation only. Stale transient authority must
        # remain stripped exactly as before.
        assert stale["scene"]["unresolved_decision"] is None
        assert stale["scene"]["observable_pressures"] == []
        assert stale["scene"]["active_questions"] == []
        assert stale["scene"]["available_reports"] == []
        assert stale["scene"]["unresolved_hooks"] == []
