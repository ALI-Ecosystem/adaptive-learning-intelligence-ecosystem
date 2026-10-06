export const DIAGNOSIS_SCHEMA_VERSION = "0.1" as const;

export type DiagnosisSchemaVersion = typeof DIAGNOSIS_SCHEMA_VERSION;

export interface DiagnosisRunRequest {
  diagnosis_run_id: string;
  learner_id: string;
  evidence_id: string;
  schema_version: DiagnosisSchemaVersion;
}

export interface SubjectReference {
  taxonomy_id: string;
  taxonomy_level?: string;
}

export type DiagnosticSourceKind =
  | "evidence"
  | "context"
  | "capability_result";

export interface DiagnosticSourceReference {
  source_kind: DiagnosticSourceKind;
  source_id: string;
}

export type DiagnosticArtifactType =
  | "information_result"
  | "capability_result";

export interface DiagnosticProducer {
  type: "information_source" | "capability";
  name: string;
  version?: string;
}

export interface DiagnosticArtifact {
  artifact_id: string;
  diagnosis_run_id: string;
  subject_ref: SubjectReference;
  artifact_type: DiagnosticArtifactType;
  producer: DiagnosticProducer;
  request: Readonly<Record<string, unknown>>;
  result: Readonly<Record<string, unknown>>;
  source_references: readonly DiagnosticSourceReference[];
  created_at: string;
  schema_version: DiagnosisSchemaVersion;
}

export interface DiagnosticFinding {
  finding_id: string;
  subject_ref: SubjectReference;
  statement: string;
  confidence: number;
  supporting_sources: readonly DiagnosticSourceReference[];
  contradicting_sources: readonly DiagnosticSourceReference[];
}

export interface RootCauseHypothesis {
  hypothesis_id: string;
  statement: string;
  confidence: number;
  explains_finding_ids: readonly string[];
  supporting_sources: readonly DiagnosticSourceReference[];
  contradicting_sources: readonly DiagnosticSourceReference[];
}

export interface StructuredDiagnosis {
  status: "completed";
  diagnosis_run_id: string;
  learner_id: string;
  subject_ref: SubjectReference;
  what: readonly DiagnosticFinding[];
  why: readonly RootCauseHypothesis[];
  schema_version: DiagnosisSchemaVersion;
}

export type UnresolvedScope = "what" | "why" | "both";

export interface UnresolvedDiagnosis {
  status: "unresolved";
  diagnosis_run_id: string;
  learner_id: string;
  subject_ref: SubjectReference;
  unresolved_scope: UnresolvedScope;
  reason: string;
  relevant_sources: readonly DiagnosticSourceReference[];
  schema_version: DiagnosisSchemaVersion;
}

export type DiagnosisRunResult = StructuredDiagnosis | UnresolvedDiagnosis;
