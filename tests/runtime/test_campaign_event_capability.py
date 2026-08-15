from pathlib import Path

from sword_runtime.api.stable_operations import StableCampaignOperations
from sword_runtime.service_runtime import ProductionSwordRuntime


def test_play_context_advertises_campaign_event_boundaries(campaign: Path) -> None:
    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-campaign-event-capability",
    )
    context = StableCampaignOperations(runtime).play_context()
    assert context["limits"]["campaign_event_boundaries"] is True
