"""Common descriptive contract for diagnostic capabilities."""

from __future__ import annotations

from .common import ContractModel, NonEmptyStr


class CapabilityMetadata(ContractModel):
    """Describe a diagnostic instrument and the limits of interpreting its output.

    Input and output contracts are descriptions; concrete capabilities own their
    payload validation and uncertainty representation.
    """

    name: NonEmptyStr
    purpose: NonEmptyStr
    supported_evidence: tuple[NonEmptyStr, ...]
    required_context: tuple[NonEmptyStr, ...]
    applicability: NonEmptyStr
    input_contract: NonEmptyStr
    output_contract: NonEmptyStr
    limitations: NonEmptyStr
    confidence_uncertainty_semantics: NonEmptyStr
    research_basis: NonEmptyStr
    implementation_version: NonEmptyStr
