"""Shared types and configuration for diagnosis contracts."""

from __future__ import annotations

from typing import Annotated, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DIAGNOSIS_SCHEMA_VERSION: Final = "0.1"
"""Current version used by Diagnosis Engine requests, artifacts, and outcomes."""

SchemaVersion: TypeAlias = Literal["0.1"]
"""Supported schema version for serialized diagnosis contracts."""

NonEmptyStr: TypeAlias = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
"""Contract text with surrounding whitespace removed and at least one character."""

Confidence: TypeAlias = Annotated[float, Field(ge=0.0, le=1.0)]
"""Confidence score from zero to one for a finding or root-cause hypothesis."""


class ContractModel(BaseModel):
    """Base model for stable domain contracts.

    Contracts reject unknown fields and are immutable at the top level so that
    runtime-specific concerns cannot silently leak into persisted domain data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
