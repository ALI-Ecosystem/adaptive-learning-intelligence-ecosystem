"""Application access boundaries for the ALI Diagnosis Engine."""

from .information_access import DiagnosticInformationSource
from .information_access.gateway import InformationGateway

__all__ = ["DiagnosticInformationSource", "InformationGateway"]
