"""One focused contract test for SCRUM-6 core invariants."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ali_diagnosis.domain import (
    DiagnosticArtifact,
    DiagnosticArtifactType,
    DiagnosticFinding,
    DiagnosticProducer,
    DiagnosticProducerType,
    DiagnosticSourceKind,
    DiagnosticSourceReference,
    DiagnosisRunRequest,
    RootCauseHypothesis,
    StructuredDiagnosis,
    SubjectReference,
    UnresolvedDiagnosis,
    UnresolvedScope,
)


def test_scrum_6_core_contract_invariants() -> None:
    subject = SubjectReference(taxonomy_id="tax_recursion", taxonomy_level="concept")
    evidence = DiagnosticSourceReference(
        source_kind=DiagnosticSourceKind.EVIDENCE,
        source_id="ev_1",
    )

    request = DiagnosisRunRequest(
        diagnosis_run_id="diag_run_1",
        learner_id="learner_1",
        evidence_id="ev_1",
    )
    assert request.schema_version == "0.1"

    with pytest.raises(ValidationError):
        DiagnosisRunRequest(
            diagnosis_run_id="diag_run_1",
            learner_id="learner_1",
            evidence_id="",
        )

    artifact = DiagnosticArtifact(
        artifact_id="art_1",
        diagnosis_run_id="diag_run_1",
        subject_ref=subject,
        artifact_type=DiagnosticArtifactType.INFORMATION_RESULT,
        producer=DiagnosticProducer(
            type=DiagnosticProducerType.INFORMATION_SOURCE,
            name="learner_state",
        ),
        request={"learner_id": "learner_1", "taxonomy_id": "tax_recursion"},
        result={"mastery_score": 0.42, "confidence_score": 0.31},
        source_references=[evidence],
        created_at=datetime.now(UTC),
    )
    assert artifact.artifact_id == "art_1"

    finding = DiagnosticFinding(
        finding_id="finding_1",
        subject_ref=subject,
        problem_statement="The learner repeatedly misses the recursion base case.",
        confidence=0.82,
        supporting_sources=[evidence],
    )
    root_cause = RootCauseHypothesis(
        hypothesis_id="why_1",
        hypothesis_statement="The learner likely has a weak understanding of termination conditions.",
        confidence=0.71,
        explains_finding_ids=["finding_1"],
        supporting_sources=[
            DiagnosticSourceReference(
                source_kind=DiagnosticSourceKind.CONTEXT,
                source_id="art_1",
            )
        ],
    )

    completed = StructuredDiagnosis(
        diagnosis_run_id="diag_run_1",
        learner_id="learner_1",
        subject_ref=subject,
        what=[finding],
        why=[root_cause],
    )
    assert completed.status == "completed"

    with pytest.raises(ValidationError):
        StructuredDiagnosis(
            diagnosis_run_id="diag_run_1",
            learner_id="learner_1",
            subject_ref=subject,
            what=[finding],
            why=[],
        )

    unresolved = UnresolvedDiagnosis(
        diagnosis_run_id="diag_run_2",
        learner_id="learner_1",
        subject_ref=subject,
        unresolved_scope=UnresolvedScope.WHY,
        reason="Available sources do not support a reliable root-cause conclusion.",
        relevant_sources=[evidence],
    )
    assert unresolved.status == "unresolved"
