"""Compose the single adaptive Diagnosis graph, evolved from SCRUM-11."""

from collections.abc import Callable
from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ali_diagnosis.application.orchestration.budget import RunBudget
from ali_diagnosis.application.orchestration.contracts import Stage, StageAgent
from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application.orchestration.tools import DiagnosisTools
from .nodes import execute_stage
from .routing import route_stage


def build_diagnosis_graph(
    *,
    agent: StageAgent,
    make_tools: Callable[[DiagnosisRuntimeState], DiagnosisTools],
    budget: RunBudget,
) -> CompiledStateGraph:
    """Wire four revisitable goals with injected per-run dependencies, no mock defaults."""
    builder = StateGraph(DiagnosisRuntimeState)
    stages: tuple[Stage, ...] = ("what", "why", "synthesis", "validation")
    for stage in stages:
        builder.add_node(stage, partial(
            execute_stage, stage=stage, agent=agent, make_tools=make_tools, budget=budget,
        ))
        builder.add_conditional_edges(stage, route_stage, {s: s for s in (*stages, END)})
    builder.add_edge(START, "what")
    return builder.compile().with_config(recursion_limit=budget.limits.max_stage_visits + 2)
