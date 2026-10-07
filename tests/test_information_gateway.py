"""Verify the information boundary, explicit example provenance, and replacement."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from ali_diagnosis.application.information_access import DiagnosticInformationSource
from ali_diagnosis.application.information_access.gateway import InformationGateway
from ali_diagnosis.domain import DiagnosisRunRequest
from ali_diagnosis.infrastructure.example_information_provider import (
    ExampleInformationProvider,
)


def test_example_response_is_explicitly_temporary_and_serializable() -> None:
    gateway = InformationGateway({"example": ExampleInformationProvider()})

    information = gateway.get_information(
        DiagnosisRunRequest(
            diagnosis_run_id="run-123",
            learner_id=" learner-123 ",
            evidence_id="evidence-123",
        )
    )

    serialized = json.loads(json.dumps(information))
    assert serialized["example"]["message"] == "Temporary example diagnostic information."
    provenance = serialized["example"]["provenance"]
    assert provenance["source_name"] == "temporary_example_information"
    assert provenance["is_temporary_example"] is True
    assert provenance["real_source_connected"] is False
    assert "No real information source is connected" in provenance["notice"]
    assert "not diagnostic evidence" in provenance["notice"]
    assert serialized == information


def test_example_requests_do_not_share_mutable_data() -> None:
    gateway = InformationGateway({"example": ExampleInformationProvider()})
    first = gateway.get_information(
        DiagnosisRunRequest(
            diagnosis_run_id="run-a",
            learner_id="learner-a",
            evidence_id="evidence-a",
        )
    )
    first["example"]["message"] = "Caller-local change"
    first["example"]["provenance"]["notice"] = "Caller-local provenance change"

    second = gateway.get_information(
        DiagnosisRunRequest(
            diagnosis_run_id="run-b",
            learner_id="learner-b",
            evidence_id="evidence-b",
        )
    )

    assert second["example"]["message"] != "Caller-local change"
    assert second["example"]["provenance"]["notice"] != "Caller-local provenance change"


def test_provider_can_be_replaced_without_changing_gateway_usage() -> None:
    requests: list[DiagnosisRunRequest] = []
    expected = {"message": "Replacement test response"}

    class ReplacementProvider:
        def get_information(
            self, request: DiagnosisRunRequest
        ) -> dict[str, Any]:
            requests.append(request)
            return expected

    gateway = InformationGateway({"replacement": ReplacementProvider()})
    request = DiagnosisRunRequest(
        diagnosis_run_id="run-123",
        learner_id="learner-123",
        evidence_id="evidence-123",
        schema_version="0.1",
    )

    assert gateway.get_information(request)["replacement"] is expected
    assert requests == [request]
    assert requests[0] is request
    assert requests[0].model_dump() == {
        "diagnosis_run_id": "run-123",
        "learner_id": "learner-123",
        "evidence_id": "evidence-123",
        "schema_version": "0.1",
    }


def test_multiple_sources_receive_the_same_request_and_keep_distinct_results() -> None:
    calls: list[tuple[str, DiagnosisRunRequest]] = []
    first_result = {"message": "First test response", "items": [1, 2]}
    second_result = {"message": "Second test response", "context": {"text": "Test"}}

    class FirstSource:
        def get_information(self, request: DiagnosisRunRequest) -> dict[str, Any]:
            calls.append(("first", request))
            return first_result

    class SecondSource:
        def get_information(self, request: DiagnosisRunRequest) -> dict[str, Any]:
            calls.append(("second", request))
            return second_result

    sources: dict[str, DiagnosticInformationSource] = {
        "first": FirstSource(),
        "second": SecondSource(),
    }
    gateway = InformationGateway(sources)
    sources.clear()
    request = DiagnosisRunRequest(
        diagnosis_run_id="run-123",
        learner_id="learner-123",
        evidence_id="evidence-123",
    )

    information = gateway.get_information(request)

    assert information == {"first": first_result, "second": second_result}
    assert calls == [("first", request), ("second", request)]
    assert all(received is request for _, received in calls)
    assert information["first"] is first_result
    assert information["second"] is second_result


def test_provider_error_propagates_without_example_fallback() -> None:
    class FailingProvider:
        def get_information(
            self, request: DiagnosisRunRequest
        ) -> dict[str, Any]:
            raise RuntimeError("Source unavailable")

    gateway = InformationGateway({"failing": FailingProvider()})

    with pytest.raises(RuntimeError, match="Source unavailable"):
        gateway.get_information(
            DiagnosisRunRequest(
                diagnosis_run_id="run-123",
                learner_id="learner-123",
                evidence_id="evidence-123",
            )
        )


@pytest.mark.parametrize("learner_id", ["", "   "])
def test_request_rejects_empty_learner_id(learner_id: str) -> None:
    with pytest.raises(ValidationError):
        DiagnosisRunRequest(
            diagnosis_run_id="run-123",
            learner_id=learner_id,
            evidence_id="evidence-123",
        )


@pytest.mark.parametrize("extra_field", ["table", "subject_ref"])
def test_request_rejects_source_details(
    extra_field: str,
) -> None:
    with pytest.raises(ValidationError):
        DiagnosisRunRequest.model_validate(
            {
                "diagnosis_run_id": "run-123",
                "learner_id": "learner-123",
                "evidence_id": "evidence-123",
                extra_field: "unexpected",
            }
        )
