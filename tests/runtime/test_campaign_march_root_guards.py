from pathlib import Path


def test_campaign_march_route_does_not_read_staff_scheme_or_define_dispatch_mixin():
    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime/sword_runtime/campaign_march_lifecycle.py").read_text()
    assert "build_campaign_dossier" not in source
    assert "command_assignments" not in source
    assert "CampaignMarchLifecycleMixin" not in source


def test_campaign_subordinate_order_owner_never_moves_formations():
    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime/sword_runtime/campaign_subordinate_orders.py").read_text()
    assert "_autonomy_move_formation_step" not in source
    assert "formation_move" not in source
    assert "location_ref\"] =" not in source


def test_campaign_march_is_registered_in_central_time_integration():
    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime/sword_runtime/time_integration.py").read_text()
    assert '"campaign_march": {"owner": "campaign_march_lifecycle", "wake": "never"}' in source
    assert "settle_campaign_march_host(planner, host, due_text)" in source
    assert "sync_campaign_subordinate_orders(self, at=at)" in source
    assert "sync_campaign_march_routes(self, runtime, at=at)" in source
