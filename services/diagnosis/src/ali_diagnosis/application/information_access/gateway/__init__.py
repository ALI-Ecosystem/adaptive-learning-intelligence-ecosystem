"""Unified gateway for diagnostic information access."""

from .diagnostic_information_source import DiagnosticInformationSource
from .information_gateway import InformationGateway

__all__ = ["DiagnosticInformationSource", "InformationGateway"]
