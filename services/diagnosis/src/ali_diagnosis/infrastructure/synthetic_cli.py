"""Opt-in real-model synthetic runner; emits only approved outcomes and artifacts."""

import argparse
import asyncio
import json
import os
import sys

from ali_diagnosis.application.orchestration.budget import RunLimits
from ali_diagnosis.application.orchestration.contracts import DiagnosisRuntime
from ali_diagnosis.application.orchestration.errors import DiagnosisExecutionError
from ali_diagnosis.domain import DiagnosisRunRequest
from ali_diagnosis.infrastructure.model_configuration import ModelConfiguration, create_stage_agent
from ali_diagnosis.infrastructure.synthetic_scenarios import SCENARIOS, synthetic_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    args = parser.parse_args()
    try:
        config = ModelConfiguration.from_environment()
        limits = RunLimits.model_validate_json(os.environ["ALI_DIAGNOSIS_LIMITS"])
        if args.scenario == "iteration_limit":
            limits = limits.model_copy(update={"max_stage_visits": 1})
        runtime: DiagnosisRuntime = synthetic_runtime(create_stage_agent(config, limits), limits, args.scenario)
        report = asyncio.run(runtime.run(DiagnosisRunRequest(
            diagnosis_run_id=f"synthetic-{args.scenario}", learner_id="synthetic-learner",
            evidence_id=f"synthetic-evidence-{args.scenario}",
        )))
        print(json.dumps({
            "outcome": report.outcome.model_dump(mode="json"),
            "artifacts": [artifact.model_dump(mode="json") for artifact in report.artifacts],
            "resource_limit_reason": report.resource_limit_reason,
            "partial_findings": [finding.model_dump(mode="json") for finding in report.partial_findings],
            "partial_hypotheses": [hypothesis.model_dump(mode="json") for hypothesis in report.partial_hypotheses],
            "metrics": {"stage_visits": report.stage_visits, "model_calls": report.model_calls,
                        "tool_calls": report.tool_calls, "reserved_cost_usd": report.reserved_cost_usd},
        }, ensure_ascii=False, indent=2))
        return 0
    except DiagnosisExecutionError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except (KeyError, ValueError):
        print("Invalid or missing ALI_DIAGNOSIS_MODEL_CONFIG / ALI_DIAGNOSIS_LIMITS configuration.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
