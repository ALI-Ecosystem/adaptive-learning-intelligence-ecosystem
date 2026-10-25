"""Real-model acceptance on synthetic data. Never enabled by the default suite."""

import asyncio
import os

import pytest

from ali_diagnosis.application.orchestration.budget import RunLimits
from ali_diagnosis.application.orchestration.errors import DiagnosisExecutionError, ResourceLimitError
from ali_diagnosis.domain import DiagnosisRunRequest
from ali_diagnosis.infrastructure.model_configuration import ModelConfiguration, create_stage_agent
from ali_diagnosis.infrastructure.synthetic_scenarios import SCENARIOS, synthetic_runtime

pytestmark = [pytest.mark.live, pytest.mark.skipif(
    os.environ.get("ALI_DIAGNOSIS_RUN_LIVE") != "1", reason="Real-model tests require explicit opt-in",
)]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_real_agent_synthetic_case(scenario):
    config = ModelConfiguration.from_environment()
    limits = RunLimits.model_validate_json(os.environ["ALI_DIAGNOSIS_LIMITS"])
    if scenario == "iteration_limit":
        limits = limits.model_copy(update={"max_stage_visits": 1})
    runtime = synthetic_runtime(create_stage_agent(config, limits), limits, scenario)
    request = DiagnosisRunRequest(diagnosis_run_id=f"live-{scenario}", learner_id="synthetic-learner",
                                   evidence_id=f"synthetic-{scenario}")
    if scenario == "iteration_limit":
        with pytest.raises(ResourceLimitError, match="iteration limit"):
            asyncio.run(runtime.run(request))
        return
    if scenario == "tool_failure":
        with pytest.raises(DiagnosisExecutionError, match="Unrecovered tool failures"):
            asyncio.run(runtime.run(request))
        return
    report = asyncio.run(runtime.run(request))
    assert report.model_calls > 0
    assert report.outcome.diagnosis_run_id == request.diagnosis_run_id
    assert report.outcome.status == ("unresolved" if scenario in ("insufficient", "contradictory") else "completed")
    assert report.model_calls <= limits.max_model_calls
    assert report.tool_calls <= limits.max_tool_calls
    assert report.reserved_cost_usd <= limits.max_cost_usd
    assert all(a.result.get("is_synthetic") or a.result.get("output", {}).get("is_synthetic")
               for a in report.artifacts)
    if scenario in ("additional_information", "contradictory", "refinement"):
        assert any(a.producer == "synthetic:history" for a in report.artifacts)
    if scenario == "capability_selection":
        assert any(a.producer == "synthetic-response-tracing" for a in report.artifacts)
    if scenario == "refinement":
        assert report.stage_visits > 4, "Acceptance requires demonstrated revisiting, not just linear success"


def test_live_alternate_provider_same_application_contract():
    alternate = os.environ.get("ALI_DIAGNOSIS_ALTERNATE_MODEL_CONFIG")
    if not alternate:
        pytest.skip("An alternate provider configuration is required for live substitution")
    primary = ModelConfiguration.from_environment()
    config = ModelConfiguration.model_validate_json(alternate)
    assert config.provider != primary.provider
    limits = RunLimits.model_validate_json(os.environ["ALI_DIAGNOSIS_LIMITS"])
    report = asyncio.run(synthetic_runtime(create_stage_agent(config, limits), limits, "success").run(
        DiagnosisRunRequest(diagnosis_run_id="live-alternate", learner_id="synthetic-learner",
                            evidence_id="synthetic-evidence")))
    assert report.outcome.status == "completed"
