from pathlib import Path


def test_mcp_preview_uses_authoritative_campaign_world_time_for_command_identity():
    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime/sword_runtime/api/mcp.py").read_text(encoding="utf-8")
    assert 'submitted_at=str(campaign["world_time"])' in source
    assert "datetime.now" not in source
