"""Deterministic doubles used against the production graph, never a mock graph."""

from ali_diagnosis.application.orchestration.contracts import (
    WhatDecision, WhyDecision, SynthesisDecision, ValidationDecision,
)
from ali_diagnosis.domain import (
    DiagnosticFinding, DiagnosticSourceReference, RootCauseHypothesis, StructuredDiagnosis,
)


def reference(source_id="evidence", kind="evidence"):
    return DiagnosticSourceReference(source_kind=kind, source_id=source_id)


def finding(case):
    return DiagnosticFinding(finding_id="f", subject_ref=case.subject_ref,
                             problem_statement="Synthetic fraction addition error.", confidence=0.6,
                             supporting_sources=[reference()])


class ScriptedAgent:
    """An injected stage implementation; all retrieval still uses the real boundary."""

    def __init__(self, *, unresolved=False, refine=False, capability=False):
        self.unresolved, self.refine, self.capability = unresolved, refine, capability
        self.visits = []

    async def run_stage(self, case, tools, budget):
        self.visits.append(case.current_stage)
        if case.current_stage == "validation" and case.finalization_reason:
            return ValidationDecision(decision="accept" if case.synthesis_candidate else "unresolved",
                                      reason="Assessing the available synthetic evidence at the resource boundary.")
        if case.current_stage == "what":
            if not case.artifacts:
                assert "artifact" in await tools.call("get_information", {"source": "trigger"})
            if self.unresolved:
                await tools.call("get_information", {"source": "history"})
                return WhatDecision(findings=[], next_stage="validation")
            return WhatDecision(findings=[finding(case)], next_stage="why")
        if case.current_stage == "why":
            if self.refine and self.visits.count("why") == 1:
                await tools.call("get_information", {"source": "history"})
                return WhyDecision(hypotheses=[], next_stage="what")
            sources = [reference()]
            if self.capability:
                metadata = await tools.call("discover_capabilities", {})
                name = metadata["capabilities"][0]["name"]
                result = await tools.call("invoke_capability", {
                    "name": name, "inputs": {"artifact_id": "run:trigger"},
                    "source_references": [reference().model_dump(mode="json")],
                })
                sources = [reference(result["artifact"]["artifact_id"], "capability_result")]
            return WhyDecision(hypotheses=[RootCauseHypothesis(
                hypothesis_id="h", hypothesis_statement="Synthetic separate-denominator procedure hypothesis.",
                confidence=0.6, explains_finding_ids=["f"], supporting_sources=sources,
            )], next_stage="synthesis")
        if case.current_stage == "synthesis":
            return SynthesisDecision(candidate=StructuredDiagnosis(
                diagnosis_run_id=case.request.diagnosis_run_id, learner_id=case.request.learner_id,
                subject_ref=case.subject_ref, what=case.what_findings, why=case.why_hypotheses,
            ), next_stage="validation")
        return ValidationDecision(decision="unresolved" if self.unresolved else "accept",
                                  reason="Insufficient corroboration." if self.unresolved else "Synthetic sources support this candidate.")


