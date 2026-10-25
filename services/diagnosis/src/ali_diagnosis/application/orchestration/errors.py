"""Safe technical failures, deliberately separate from educational uncertainty."""


class DiagnosisExecutionError(RuntimeError):
    """A technical failure prevented a valid diagnostic result."""


class ResourceLimitError(DiagnosisExecutionError):
    """A run exhausted its configured execution budget."""


class FinalAssessmentRequired(DiagnosisExecutionError):
    """Internal handover signal: preserve remaining resources for validation."""


class ProviderError(DiagnosisExecutionError):
    """The model provider failed; raw provider details are not exposed."""


class InvalidDecisionError(DiagnosisExecutionError):
    """An agent decision violated a structural or provenance invariant."""


class ToolRejectedError(ValueError):
    """A recoverable invalid selection, argument, or applicability decision."""
