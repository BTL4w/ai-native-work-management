"""Stable bounded graph topology for one Assignment Specialist run."""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from work_management_ai.agents.assignment.contracts import (
    AssignmentAgentInput,
    AssignmentAgentOutput,
    AssignmentExplanation,
    ExplicitAssignmentSnapshot,
    ProjectWorkloadSnapshot,
    TeamRecommendationSnapshot,
    TeamRequirementsPendingSnapshot,
    WorkloadExplanation,
)
from work_management_ai.runtime.contracts import (
    AgentHandoff,
    AgentResult,
    ResolvedActorContext,
    ToolExecutionResult,
)

NODES = (
    "receive_handoff",
    "validate_contract_and_policy",
    "load_skill",
    "execute_deterministic_tool",
    "generate_structured_explanation",
    "verify_result",
    "deterministic_fallback",
    "manual_fallback",
    "return_agent_result",
)

type Route = Literal[
    "execute",
    "verify",
    "deterministic_fallback",
    "manual_fallback",
]
type DeterministicSnapshot = (
    TeamRecommendationSnapshot
    | TeamRequirementsPendingSnapshot
    | ProjectWorkloadSnapshot
    | ExplicitAssignmentSnapshot
)
type Explanation = AssignmentExplanation | WorkloadExplanation


class AssignmentAgentState(TypedDict):
    handoff: AgentHandoff
    actor: ResolvedActorContext | None
    value: AssignmentAgentInput | None
    selected_skill: str | None
    skill_instructions: str
    tool_result: ToolExecutionResult | None
    snapshot: DeterministicSnapshot | None
    explanation: Explanation | None
    output: AssignmentAgentOutput | None
    result: AgentResult | None
    route: Route
    stop_reason: str
    safe_error_code: str | None
    iterations_used: int
    tool_calls_used: int
    model_refs: tuple[str, ...]


class AssignmentAgentNodeHandlers(Protocol):
    async def receive_handoff(self, state: AssignmentAgentState) -> dict[str, object]: ...

    async def validate_contract_and_policy(
        self, state: AssignmentAgentState
    ) -> dict[str, object]: ...

    async def load_skill(self, state: AssignmentAgentState) -> dict[str, object]: ...

    async def execute_deterministic_tool(
        self, state: AssignmentAgentState
    ) -> dict[str, object]: ...

    async def generate_structured_explanation(
        self, state: AssignmentAgentState
    ) -> dict[str, object]: ...

    async def verify_result(self, state: AssignmentAgentState) -> dict[str, object]: ...

    async def deterministic_fallback(self, state: AssignmentAgentState) -> dict[str, object]: ...

    async def manual_fallback(self, state: AssignmentAgentState) -> dict[str, object]: ...

    async def return_agent_result(self, state: AssignmentAgentState) -> dict[str, object]: ...


class AssignmentAgentGraph:
    def __init__(self, handlers: AssignmentAgentNodeHandlers) -> None:
        self._compiled = self._compile(handlers)

    async def run(self, state: AssignmentAgentState) -> AgentResult:
        result = await self._compiled.ainvoke(state)
        output = result["result"]
        if output is None:
            raise RuntimeError("assignment agent graph completed without a result")
        return output

    @staticmethod
    def _compile(
        handlers: AssignmentAgentNodeHandlers,
    ) -> CompiledStateGraph[AssignmentAgentState, None, AssignmentAgentState, AssignmentAgentState]:
        builder = StateGraph(AssignmentAgentState)
        for name in NODES:
            builder.add_node(name, getattr(handlers, name))
        builder.add_edge(START, "receive_handoff")
        builder.add_edge("receive_handoff", "validate_contract_and_policy")
        builder.add_conditional_edges(
            "validate_contract_and_policy",
            _route,
            {"execute": "load_skill", "manual_fallback": "manual_fallback"},
        )
        builder.add_conditional_edges(
            "load_skill",
            _route,
            {"execute": "execute_deterministic_tool", "manual_fallback": "manual_fallback"},
        )
        builder.add_conditional_edges(
            "execute_deterministic_tool",
            _route,
            {
                "execute": "generate_structured_explanation",
                "verify": "verify_result",
                "manual_fallback": "manual_fallback",
            },
        )
        builder.add_conditional_edges(
            "generate_structured_explanation",
            _route,
            {
                "verify": "verify_result",
                "deterministic_fallback": "deterministic_fallback",
                "manual_fallback": "manual_fallback",
            },
        )
        builder.add_conditional_edges(
            "verify_result",
            _route,
            {
                "execute": "return_agent_result",
                "deterministic_fallback": "deterministic_fallback",
                "manual_fallback": "manual_fallback",
            },
        )
        builder.add_edge("deterministic_fallback", "return_agent_result")
        builder.add_edge("manual_fallback", "return_agent_result")
        builder.add_edge("return_agent_result", END)
        return builder.compile()


def _route(state: AssignmentAgentState) -> Route:
    return state["route"]
