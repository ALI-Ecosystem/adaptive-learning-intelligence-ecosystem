import {
  DIAGNOSIS_SCHEMA_VERSION,
  assertValidDiagnosisRunRequest,
  assertValidDiagnosisRunResult,
  type DiagnosisRunRequest,
  type DiagnosisRunResult,
} from "../src/diagnosis/domain/index.js";

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function expectThrow(run: () => void, expectedMessage: string): void {
  let message = "";

  try {
    run();
  } catch (error) {
    message = error instanceof Error ? error.message : String(error);
  }

  assert(message.includes(expectedMessage), `Expected error containing: ${expectedMessage}`);
}

const request: DiagnosisRunRequest = {
  diagnosis_run_id: "diag_run_1",
  learner_id: "learner_1",
  evidence_id: "ev_1",
  schema_version: DIAGNOSIS_SCHEMA_VERSION,
};

assertValidDiagnosisRunRequest(request);

expectThrow(
  () => assertValidDiagnosisRunRequest({ ...request, evidence_id: "" }),
  "evidence_id is required",
);

const completed: DiagnosisRunResult = {
  status: "completed",
  diagnosis_run_id: "diag_run_1",
  learner_id: "learner_1",
  subject_ref: { taxonomy_id: "tax_recursion" },
  what: [
    {
      finding_id: "finding_1",
      subject_ref: { taxonomy_id: "tax_recursion" },
      statement: "The learner repeatedly misses the recursion base case.",
      confidence: 0.82,
      supporting_sources: [{ source_kind: "evidence", source_id: "ev_1" }],
      contradicting_sources: [],
    },
  ],
  why: [
    {
      hypothesis_id: "why_1",
      statement: "The learner may not understand the termination condition.",
      confidence: 0.71,
      explains_finding_ids: ["finding_1"],
      supporting_sources: [{ source_kind: "context", source_id: "art_1" }],
      contradicting_sources: [],
    },
  ],
  schema_version: DIAGNOSIS_SCHEMA_VERSION,
};

assertValidDiagnosisRunResult(completed);

expectThrow(
  () => assertValidDiagnosisRunResult({ ...completed, why: [] }),
  "completed diagnosis requires at least one WHY hypothesis",
);

const unresolved: DiagnosisRunResult = {
  status: "unresolved",
  diagnosis_run_id: "diag_run_2",
  learner_id: "learner_1",
  subject_ref: { taxonomy_id: "tax_recursion" },
  unresolved_scope: "why",
  reason: "Available sources do not support a reliable root-cause conclusion.",
  relevant_sources: [{ source_kind: "evidence", source_id: "ev_2" }],
  schema_version: DIAGNOSIS_SCHEMA_VERSION,
};

assertValidDiagnosisRunResult(unresolved);
