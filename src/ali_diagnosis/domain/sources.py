"""Subject and source references for diagnosis contracts."""

from __future__ import annotations

from enum import StrEnum

from .common import ContractModel, NonEmptyStr


class SubjectReference(ContractModel):
    """Reference to the existing ALI content taxonomy.

    Identifies the subject of an artifact or diagnosis by taxonomy ID and
    optional level.
    """

    taxonomy_id: NonEmptyStr
    taxonomy_level: NonEmptyStr | None = None


class DiagnosticSourceKind(StrEnum):
    """Source families that may support or contradict a diagnosis."""

    EVIDENCE = "evidence"
    CONTEXT = "context"
    CAPABILITY_RESULT = "capability_result"


class DiagnosticSourceReference(ContractModel):
    """Stable reference to evidence, retrieved context, or a capability result.

    Stores the source kind and ID so diagnostic claims can cite their sources.
    """

    source_kind: DiagnosticSourceKind
    source_id: NonEmptyStr
