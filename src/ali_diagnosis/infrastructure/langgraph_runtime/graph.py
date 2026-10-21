"""Compose the deterministic SCRUM-11 LangGraph orchestration proof."""

from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ali_diagnosis.application import CapabilityRegistry, InformationGateway

from .mock_dependencies import MockDiagnosisCapability, MockInformationSource
from .nodes.synthesis import synthesis
from .nodes.validation import MockValidationDecision, validation
from .nodes.what import what
from .nodes.why import why
from .routing import route_validation
from .state import DiagnosisRuntimeState

MAX_REFINEMENT_LOOPS = 5


def build_diagnosis_graph(
    *,
    information_gateway: InformationGateway | None = None,
    capability_registry: CapabilityRegistry | None = None,
    validation_decisions: tuple[MockValidationDecision, ...] = ("accept",),
    max_refinement_loops: int = MAX_REFINEMENT_LOOPS,
) -> CompiledStateGraph:
    """Compile mock WHAT/WHY/synthesis/validation with bounded refinement.

    Decisions are a deterministic test script, indexed by completed iterations;
    the last decision repeats. The loop limit bounds requests that route back
    to WHAT/WHY. Dependency errors propagate as execution errors, not diagnoses.
    Each invocation starts with fresh per-run state; dependencies are stateless.
    """
    if max_refinement_loops < 0:
        raise ValueError("max_refinement_loops must be non-negative")
    decisions = tuple(validation_decisions)
    if not decisions or any(value not in ("accept", "what", "why") for value in decisions):
        raise ValueError("validation_decisions must contain accept, what, or why")
    if information_gateway is None:
        information_gateway = InformationGateway({"mock": MockInformationSource()})
    if capability_registry is None:
        capability_registry = CapabilityRegistry()
        capability_registry.register(MockDiagnosisCapability())

    builder = StateGraph(DiagnosisRuntimeState)
    builder.add_node("what", partial(what, information_gateway=information_gateway))
    builder.add_node("why", partial(why, capability_registry=capability_registry))
    builder.add_node("synthesis", synthesis)
    builder.add_node(
        "validation",
        partial(validation, decisions=decisions, max_refinement_loops=max_refinement_loops),
    )
    builder.add_edge(START, "what")
    builder.add_edge("what", "why")
    builder.add_edge("why", "synthesis")
    builder.add_edge("synthesis", "validation")
    builder.add_conditional_edges(
        "validation", route_validation, {END: END, "what": "what", "why": "why"}
    )
    # Allow all bounded iterations to finish before LangGraph's step guard.
    return builder.compile().with_config(recursion_limit=4 * (max_refinement_loops + 1) + 1)
