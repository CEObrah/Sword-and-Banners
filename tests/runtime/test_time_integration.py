from __future__ import annotations

from sword_runtime.production_planner import ProductionCampaignPlanner as DomainProductionPlanner
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner as HostedProductionPlanner
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


def test_hosted_runtime_has_one_named_chronology_orchestration_authority():
    assert HostedProductionPlanner._advance_runtime is ProductionTimeIntegrationMixin._advance_runtime
    assert HostedProductionPlanner._advance_runtime.__module__ == "sword_runtime.time_integration"
    # The domain composition intentionally contains mechanics and settlement hooks,
    # but must not grow a second top-level scheduler loop beside time_integration.
    assert "_advance_runtime" not in DomainProductionPlanner.__dict__


def test_time_integration_precedes_domain_settlement_mixins_in_hosted_mro():
    mro = list(HostedProductionPlanner.__mro__)
    assert mro.index(ProductionTimeIntegrationMixin) < mro.index(DomainProductionPlanner)
    assert mro[1] is ProductionTimeIntegrationMixin
