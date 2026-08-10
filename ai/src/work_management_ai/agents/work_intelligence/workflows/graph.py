"""Stable graph topology for one bounded Work Intelligence run."""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from work_management_ai.agents.work_intelligence.contracts import (
    EvidenceItem,
    GroundedAnswerDraft,
    WorkIntelligenceInput,
    WorkIntelligenceOutput,
    WorkStepPlan,
)
from work_management_ai.runtime.contracts import AgentHandoff, AgentResult, ToolExecutionResult

NODES = (
    "receive_handoff",
    "validate_contract",
    "build_specialist_context",
    "create_step_plan",
    "load_answer_work_question_skill",
    "execute_allowed_read_tool",
    "synthesize_grounded_answer",
    "verify_result",
    "manual_read_fallback",
    "return_agent_result",
)

type Route = Literal[
    "execute",
    "requested_handoff",
    "awaiting_input",
    "not_found",
    "manual_fallback",
]


class WorkIntelligenceState(TypedDict):
    handoff: AgentHandoff
    value: WorkIntelligenceInput | None
    plan: WorkStepPlan | None
    tool_result: ToolExecutionResult | None
    evidence: tuple[EvidenceItem, ...]
    draft: GroundedAnswerDraft | None
    output: WorkIntelligenceOutput | None
    result: AgentResult | None
    skill_instructions: str
    route: Route
    stop_reason: str
    safe_error_code: str | None
    iterations_used: int
    tool_calls_used: int
    model_refs: tuple[str, ...]


class WorkIntelligenceNodeHandlers(Protocol):
    async def receive_handoff(self, state: WorkIntelligenceState) -> dict[str, object]: ...

    async def validate_contract(self, state: WorkIntelligenceState) -> dict[str, object]: ...

    async def build_specialist_context(self, state: WorkIntelligenceState) -> dict[str, object]: ...

    async def create_step_plan(self, state: WorkIntelligenceState) -> dict[str, object]: ...

    async def load_answer_work_question_skill(
        self, state: WorkIntelligenceState
    ) -> dict[str, object]: ...

    async def execute_allowed_read_tool(
        self, state: WorkIntelligenceState
    ) -> dict[str, object]: ...

    async def synthesize_grounded_answer(
        self, state: WorkIntelligenceState
    ) -> dict[str, object]: ...

    async def verify_result(self, state: WorkIntelligenceState) -> dict[str, object]: ...

    async def manual_read_fallback(self, state: WorkIntelligenceState) -> dict[str, object]: ...

    async def return_agent_result(self, state: WorkIntelligenceState) -> dict[str, object]: ...


class WorkIntelligenceGraph:
    def __init__(self, handlers: WorkIntelligenceNodeHandlers) -> None:
        self._compiled = self._compile(handlers)

    async def run(self, state: WorkIntelligenceState) -> AgentResult:
        result = await self._compiled.ainvoke(state)
        output = result["result"]
        if output is None:
            raise RuntimeError("work intelligence graph completed without a result")
        return output

    @staticmethod
    def _compile(
        handlers: WorkIntelligenceNodeHandlers,
    ) -> CompiledStateGraph[
        WorkIntelligenceState, None, WorkIntelligenceState, WorkIntelligenceState
    ]:
        builder = StateGraph(WorkIntelligenceState)
        builder.add_node("receive_handoff", handlers.receive_handoff)
        builder.add_node("validate_contract", handlers.validate_contract)
        builder.add_node("build_specialist_context", handlers.build_specialist_context)
        builder.add_node("create_step_plan", handlers.create_step_plan)
        builder.add_node(
            "load_answer_work_question_skill", handlers.load_answer_work_question_skill
        )
        builder.add_node("execute_allowed_read_tool", handlers.execute_allowed_read_tool)
        builder.add_node("synthesize_grounded_answer", handlers.synthesize_grounded_answer)
        builder.add_node("verify_result", handlers.verify_result)
        builder.add_node("manual_read_fallback", handlers.manual_read_fallback)
        builder.add_node("return_agent_result", handlers.return_agent_result)

        builder.add_edge(START, "receive_handoff")
        builder.add_edge("receive_handoff", "validate_contract")
        builder.add_conditional_edges(
            "validate_contract",
            _route,
            {"execute": "build_specialist_context", "manual_fallback": "manual_read_fallback"},
        )
        builder.add_conditional_edges(
            "build_specialist_context",
            _route,
            {"execute": "create_step_plan", "manual_fallback": "manual_read_fallback"},
        )
        builder.add_conditional_edges(
            "create_step_plan",
            _route,
            {
                "execute": "load_answer_work_question_skill",
                "requested_handoff": "return_agent_result",
                "manual_fallback": "manual_read_fallback",
            },
        )
        builder.add_conditional_edges(
            "load_answer_work_question_skill",
            _route,
            {"execute": "execute_allowed_read_tool", "manual_fallback": "manual_read_fallback"},
        )
        builder.add_conditional_edges(
            "execute_allowed_read_tool",
            _route,
            {
                "execute": "synthesize_grounded_answer",
                "awaiting_input": "return_agent_result",
                "not_found": "return_agent_result",
                "manual_fallback": "manual_read_fallback",
            },
        )
        builder.add_conditional_edges(
            "synthesize_grounded_answer",
            _route,
            {"execute": "verify_result", "manual_fallback": "manual_read_fallback"},
        )
        builder.add_conditional_edges(
            "verify_result",
            _route,
            {"execute": "return_agent_result", "manual_fallback": "manual_read_fallback"},
        )
        builder.add_edge("manual_read_fallback", "return_agent_result")
        builder.add_edge("return_agent_result", END)
        return builder.compile()


def _route(state: WorkIntelligenceState) -> Route:
    return state["route"]
