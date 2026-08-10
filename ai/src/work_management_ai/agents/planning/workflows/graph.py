"""Stable graph topology for one Planning Specialist run."""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from work_management_ai.agents.planning.contracts import (
    PlanningAgentInput,
    PlanningAgentOutput,
    PlanningStepPlan,
)
from work_management_ai.runtime.contracts import (
    AgentHandoff,
    AgentResult,
    ResolvedActorContext,
    ToolExecutionResult,
)

NODES = (
    "receive_handoff",
    "validate_contract",
    "build_planning_context",
    "select_create_or_revision_skill",
    "create_step_plan",
    "execute_planning_tool",
    "verify_result",
    "manual_editable_fallback",
    "return_agent_result",
)

type Route = Literal["execute", "requested_handoff", "manual_fallback"]


class PlanningAgentState(TypedDict):
    handoff: AgentHandoff
    actor: ResolvedActorContext | None
    value: PlanningAgentInput | None
    selected_skill: str | None
    skill_instructions: str
    plan: PlanningStepPlan | None
    tool_result: ToolExecutionResult | None
    output: PlanningAgentOutput | None
    result: AgentResult | None
    route: Route
    stop_reason: str
    safe_error_code: str | None
    iterations_used: int
    tool_calls_used: int
    model_refs: tuple[str, ...]


class PlanningAgentNodeHandlers(Protocol):
    async def receive_handoff(self, state: PlanningAgentState) -> dict[str, object]: ...

    async def validate_contract(self, state: PlanningAgentState) -> dict[str, object]: ...

    async def build_planning_context(self, state: PlanningAgentState) -> dict[str, object]: ...

    async def select_create_or_revision_skill(
        self, state: PlanningAgentState
    ) -> dict[str, object]: ...

    async def create_step_plan(self, state: PlanningAgentState) -> dict[str, object]: ...

    async def execute_planning_tool(self, state: PlanningAgentState) -> dict[str, object]: ...

    async def verify_result(self, state: PlanningAgentState) -> dict[str, object]: ...

    async def manual_editable_fallback(self, state: PlanningAgentState) -> dict[str, object]: ...

    async def return_agent_result(self, state: PlanningAgentState) -> dict[str, object]: ...


class PlanningAgentGraph:
    def __init__(self, handlers: PlanningAgentNodeHandlers) -> None:
        self._compiled = self._compile(handlers)

    async def run(self, state: PlanningAgentState) -> AgentResult:
        result = await self._compiled.ainvoke(state)
        output = result["result"]
        if output is None:
            raise RuntimeError("planning agent graph completed without a result")
        return output

    @staticmethod
    def _compile(
        handlers: PlanningAgentNodeHandlers,
    ) -> CompiledStateGraph[PlanningAgentState, None, PlanningAgentState, PlanningAgentState]:
        builder = StateGraph(PlanningAgentState)
        builder.add_node("receive_handoff", handlers.receive_handoff)
        builder.add_node("validate_contract", handlers.validate_contract)
        builder.add_node("build_planning_context", handlers.build_planning_context)
        builder.add_node(
            "select_create_or_revision_skill", handlers.select_create_or_revision_skill
        )
        builder.add_node("create_step_plan", handlers.create_step_plan)
        builder.add_node("execute_planning_tool", handlers.execute_planning_tool)
        builder.add_node("verify_result", handlers.verify_result)
        builder.add_node("manual_editable_fallback", handlers.manual_editable_fallback)
        builder.add_node("return_agent_result", handlers.return_agent_result)

        builder.add_edge(START, "receive_handoff")
        builder.add_edge("receive_handoff", "validate_contract")
        builder.add_conditional_edges(
            "validate_contract",
            _route,
            {"execute": "build_planning_context", "manual_fallback": "manual_editable_fallback"},
        )
        builder.add_conditional_edges(
            "build_planning_context",
            _route,
            {
                "execute": "select_create_or_revision_skill",
                "manual_fallback": "manual_editable_fallback",
            },
        )
        builder.add_conditional_edges(
            "select_create_or_revision_skill",
            _route,
            {"execute": "create_step_plan", "manual_fallback": "manual_editable_fallback"},
        )
        builder.add_conditional_edges(
            "create_step_plan",
            _route,
            {
                "execute": "execute_planning_tool",
                "requested_handoff": "return_agent_result",
                "manual_fallback": "manual_editable_fallback",
            },
        )
        builder.add_conditional_edges(
            "execute_planning_tool",
            _route,
            {"execute": "verify_result", "manual_fallback": "manual_editable_fallback"},
        )
        builder.add_conditional_edges(
            "verify_result",
            _route,
            {"execute": "return_agent_result", "manual_fallback": "manual_editable_fallback"},
        )
        builder.add_edge("manual_editable_fallback", "return_agent_result")
        builder.add_edge("return_agent_result", END)
        return builder.compile()


def _route(state: PlanningAgentState) -> Route:
    return state["route"]
