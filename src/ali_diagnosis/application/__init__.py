"""Application access boundaries for the ALI Diagnosis Engine."""

from .capabilities.capability_registry import CapabilityRegistry
from .capabilities.diagnostic_capability import DiagnosticCapability
from .information_access import DiagnosticInformationSource
from .information_access.gateway import InformationGateway

__all__ = [
    "CapabilityRegistry",
    "DiagnosticCapability",
    "DiagnosticInformationSource",
    "InformationGateway",
]
