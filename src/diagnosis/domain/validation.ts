import {
  DIAGNOSIS_SCHEMA_VERSION,
  type DiagnosticArtifact,
  type DiagnosisRunRequest,
  type DiagnosisRunResult,
} from "./contracts.js";

function requireNonEmpty(value: string, field: string): void {
  if (value.trim().length === 0) {
    throw new Error(`${field} is required`);
  }
}

function requireConfidence(value: number, field: string): void {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error(`${field} must be between 0 and 1`);
  }
}

export function assertValidDiagnosisRunRequest(
  request: DiagnosisRunRequest,
): void {
  requireNonEmpty(request.diagnosis_run_id, "diagnosis_run_id");
  requireNonEmpty(request.learner_id, "learner_id");
  requireNonEmpty(request.evidence_id, "evidence_id");

  if (request.schema_version !== DIAGNOSIS_SCHEMA_VERSION) {
    throw new Error("unsupported schema_version");
  }
}

export function assertValidDiagnosticArtifact(
  artifact: DiagnosticArtifact,
): void {
  requireNonEmpty(artifact.artifact_id, "artifact_id");
  requireNonEmpty(artifact.diagnosis_run_id, "diagnosis_run_id");
  requireNonEmpty(artifact.subject_ref.taxonomy_id, "subject_ref.taxonomy_id");
  requireNonEmpty(artifact.producer.name, "producer.name");
  requireNonEmpty(artifact.created_at, "created_at");

  if (artifact.schema_version !== DIAGNOSIS_SCHEMA_VERSION) {
    throw new Error("unsupported schema_version");
  }
}

export function assertValidDiagnosisRunResult(result: DiagnosisRunResult): void {
  requireNonEmpty(result.diagnosis_run_id, "diagnosis_run_id");
  requireNonEmpty(result.learner_id, "learner_id");
  requireNonEmpty(result.subject_ref.taxonomy_id, "subject_ref.taxonomy_id");

  if (result.schema_version !== DIAGNOSIS_SCHEMA_VERSION) {
    throw new Error("unsupported schema_version");
  }

  if (result.status === "unresolved") {
    requireNonEmpty(result.reason, "reason");
    return;
  }

  if (result.what.length === 0) {
    throw new Error("completed diagnosis requires at least one WHAT finding");
  }

  if (result.why.length === 0) {
    throw new Error("completed diagnosis requires at least one WHY hypothesis");
  }

  const findingIds = new Set<string>();

  for (const finding of result.what) {
    requireNonEmpty(finding.finding_id, "finding_id");
    requireNonEmpty(finding.statement, "finding.statement");
    requireNonEmpty(finding.subject_ref.taxonomy_id, "finding.subject_ref.taxonomy_id");
    requireConfidence(finding.confidence, "finding.confidence");
    findingIds.add(finding.finding_id);
  }

  for (const hypothesis of result.why) {
    requireNonEmpty(hypothesis.hypothesis_id, "hypothesis_id");
    requireNonEmpty(hypothesis.statement, "hypothesis.statement");
    requireConfidence(hypothesis.confidence, "hypothesis.confidence");

    if (hypothesis.explains_finding_ids.length === 0) {
      throw new Error("WHY hypothesis must explain at least one WHAT finding");
    }

    for (const findingId of hypothesis.explains_finding_ids) {
      if (!findingIds.has(findingId)) {
        throw new Error(`WHY references unknown WHAT finding: ${findingId}`);
      }
    }
  }
}
