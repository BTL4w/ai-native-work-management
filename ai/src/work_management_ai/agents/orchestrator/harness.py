"""Guarded runtime for bounded Orchestrator planning and delegation."""

import asyncio
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from work_management_ai.agents.orchestrator.contracts import (
    ActorContextResolverPort,
    ExecutionPlan,
    ExecutionStep,
    OrchestratorInput,
    OrchestratorOutput,
    OrchestratorStatus,
    OrchestratorSynthesis,
    SpecialistRunnerPort,
    StepMode,
)
from work_management_ai.agents.orchestrator.evaluators.plan import (
    ExecutionPlanError,
    ready_batches,
    validate_execution_plan,
    validate_replan,
)
from work_management_ai.agents.orchestrator.prompts import (
    build_plan_messages,
    build_synthesis_messages,
)
from work_management_ai.agents.orchestrator.workflows.graph import (
    OrchestratorGraph,
    OrchestratorState,
)
from work_management_ai.model_gateway.contracts import ModelGateway, StructuredModelRequest
from work_management_ai.model_gateway.errors import ModelGatewayError
from work_management_ai.runtime.agent_registry import AgentRegistry
from work_management_ai.runtime.contracts import (
    AgentBudget,
    AgentHandoff,
    AgentId,
    AgentRunStatus,
    CapabilityUnavailableResponseBlock,
    JsonValue,
    QuestionResponseBlock,
    SafeErrorResponseBlock,
)
from work_management_ai.runtime.policy_guard import AgentPolicyError, PolicyGuard

_MAX_PLAN_REPAIRS = 1
_MAX_REPLANS = 2
_MAX_HANDOFFS = 6


class OrchestratorHarness:
    def __init__(
        self,
        *,
        model_gateway: ModelGateway,
        registry: AgentRegistry,
        policy_guard: PolicyGuard,
        actor_resolver: ActorContextResolverPort,
        specialists: SpecialistRunnerPort,
    ) -> None:
        self._model_gateway = model_gateway
        self._registry = registry
        self._guard = policy_guard
        self._actor_resolver = actor_resolver
        self._specialists = specialists
        self._graph = OrchestratorGraph(self)

    async def run_turn(self, value: OrchestratorInput) -> OrchestratorOutput:
        return await self._graph.run(
            OrchestratorState(
                value=value,
                current_actor=None,
                plan=None,
                prior_plan=None,
                original_plan=None,
                results=(),
                completed_step_ids=(),
                last_batch_handoffs=(),
                last_batch_results=(),
                blocks=(),
                status=OrchestratorStatus.FAILED,
                stop_reason="NOT_STARTED",
                route="execute",
                repair_attempts=0,
                replans_used=0,
                handoffs_used=0,
                model_refs=(),
                pending_requested_handoff=None,
                output=None,
            )
        )

    async def intake_turn(self, state: OrchestratorState) -> dict[str, object]:
        try:
            actor = await self._actor_resolver.resolve(state["value"].actor)
        except Exception:
            return self._failure("ACTOR_CONTEXT_UNAVAILABLE")
        if not actor.is_active:
            return self._failure("ACTOR_INACTIVE")
        if (
            actor.membership_id != state["value"].actor.membership_id
            or actor.organization_id != state["value"].actor.organization_id
        ):
            return self._failure("ACTOR_CONTEXT_MISMATCH")
        return {
            "current_actor": actor,
            "route": "execute",
            "stop_reason": "RUNNING",
        }

    async def build_context(self, state: OrchestratorState) -> dict[str, object]:
        return {}

    async def plan_objective(self, state: OrchestratorState) -> dict[str, object]:
        trusted_plan = self._trusted_planning_action_plan(state)
        if trusted_plan is not None:
            updates: dict[str, object] = {
                "plan": trusted_plan,
                "stop_reason": "RUNNING",
            }
            if state["original_plan"] is None:
                updates["original_plan"] = trusted_plan
            return updates
        requested = state["pending_requested_handoff"]
        if requested is not None:
            mode = f"replan.{state['replans_used']}"
        elif state["repair_attempts"]:
            mode = "repair"
        else:
            mode = "plan"
        request = StructuredModelRequest(
            invocation_key=f"orchestrator.{state['value'].locale}.{mode}",
            messages=build_plan_messages(
                state["value"],
                mode=mode,
                requested_handoff=requested,
                prior_plan=state["prior_plan"],
                specialist_catalog=self._registry.planning_catalog(
                    active_phase=2,
                    role=(state["current_actor"].role if state["current_actor"] else "EMPLOYEE"),
                ),
            ),
            output_schema=ExecutionPlan,
            timeout_seconds=60,
        )
        try:
            response = await self._model_gateway.generate_structured(request)
        except ModelGatewayError:
            return {"plan": None, "stop_reason": "MODEL_PLAN_INVALID"}
        updates: dict[str, object] = {
            "plan": response.parsed,
            "model_refs": (*state["model_refs"], response.model_ref),
            "stop_reason": "RUNNING",
        }
        if state["original_plan"] is None:
            updates["original_plan"] = response.parsed
        return updates

    def _trusted_planning_action_plan(self, state: OrchestratorState) -> ExecutionPlan | None:
        active = state["value"].active_context.active_planning
        if active is None:
            return None
        capability = {
            "RESUME_INPUT": "planning.resume",
            "REVISE": "planning.revise",
        }[active.requested_operation]
        actor = state["current_actor"]
        catalog = self._registry.planning_catalog(
            active_phase=2,
            role=(actor.role if actor is not None else "EMPLOYEE"),
        )
        planning_agent = next(
            (
                item
                for item in catalog
                if item["agent_id"] == AgentId.PLANNING.value
                and capability in cast(list[object], item["capabilities"])
            ),
            None,
        )
        if planning_agent is None:
            return ExecutionPlan(
                objectives=(state["value"].message,),
                unavailable_capabilities=(capability,),
                response_language=state["value"].locale,
            )
        return ExecutionPlan(
            objectives=(state["value"].message,),
            steps=(
                ExecutionStep(
                    step_id=(
                        "resume_planning"
                        if active.requested_operation == "RESUME_INPUT"
                        else "revise_plan"
                    ),
                    target_agent_id=AgentId.PLANNING,
                    target_agent_version=str(planning_agent["agent_version"]),
                    capability=capability,
                    objective=state["value"].message,
                    typed_input={},
                    mode=StepMode.PROPOSAL,
                ),
            ),
            response_language=state["value"].locale,
        )

    async def validate_plan(self, state: OrchestratorState) -> dict[str, object]:
        plan = state["plan"]
        if plan is None:
            if (
                state["repair_attempts"] < _MAX_PLAN_REPAIRS
                and state["pending_requested_handoff"] is None
            ):
                return {"route": "repair"}
            return {"route": "manual_fallback", "stop_reason": "MODEL_PLAN_INVALID"}
        actor = state["current_actor"]
        if actor is None:
            return self._failure("ACTOR_CONTEXT_UNAVAILABLE")
        try:
            validate_execution_plan(plan, self._registry, actor)
            if plan.response_language != state["value"].locale:
                raise ExecutionPlanError("RESPONSE_LANGUAGE_MISMATCH")
            requested = state["pending_requested_handoff"]
            prior = state["prior_plan"]
            if requested is not None and prior is not None:
                validate_replan(
                    prior=prior,
                    candidate=plan,
                    completed_step_ids=frozenset(state["completed_step_ids"]),
                    requested_handoff=requested,
                )
        except ExecutionPlanError:
            if (
                state["repair_attempts"] < _MAX_PLAN_REPAIRS
                and state["pending_requested_handoff"] is None
            ):
                return {"route": "repair", "stop_reason": "EXECUTION_PLAN_INVALID"}
            return {"route": "manual_fallback", "stop_reason": "EXECUTION_PLAN_INVALID"}
        if not plan.steps and plan.unavailable_capabilities:
            return {"route": "capability_unavailable"}
        return {"route": "execute", "pending_requested_handoff": None}

    async def select_next_step(self, state: OrchestratorState) -> dict[str, object]:
        plan = state["plan"]
        if plan is None:
            return self._failure("EXECUTION_PLAN_MISSING")
        if len(state["completed_step_ids"]) == len(plan.steps):
            return {"route": "synthesize"}
        batches = ready_batches(plan, frozenset(state["completed_step_ids"]))
        if not batches:
            return self._failure("NO_READY_EXECUTION_STEP")
        return {"route": "delegate"}

    async def delegate_specialist(self, state: OrchestratorState) -> dict[str, object]:
        plan = state["plan"]
        actor = state["current_actor"]
        if plan is None or actor is None:
            return self._failure("ORCHESTRATOR_STATE_INVALID")
        batch = ready_batches(plan, frozenset(state["completed_step_ids"]))[0]
        if state["handoffs_used"] + len(batch) > _MAX_HANDOFFS:
            return self._failure("HANDOFF_BUDGET_EXHAUSTED")
        handoffs: list[AgentHandoff] = []
        for step in batch:
            registered = self._registry.resolve(
                step.target_agent_id,
                step.target_agent_version,
                active_phase=2,
            )
            runtime = registered.manifest.runtime
            handoff = AgentHandoff(
                orchestration_run_id=(
                    state["value"].orchestration_run_id
                    or uuid5(NAMESPACE_URL, f"orchestration:{state['value'].turn_id}")
                ),
                parent_agent_run_id=uuid5(NAMESPACE_URL, f"orchestrator:{state['value'].turn_id}"),
                target_agent_id=step.target_agent_id,
                target_agent_version=step.target_agent_version,
                capability=step.capability,
                objective=step.objective,
                typed_input=self._trusted_specialist_input(step, state["value"]),
                context_references=(),
                actor=state["value"].actor,
                budget=AgentBudget(
                    max_iterations=runtime.max_iterations,
                    max_tool_calls=runtime.max_tool_calls,
                    max_handoffs=runtime.max_handoffs,
                    max_replans=runtime.max_replans,
                    timeout_seconds=runtime.timeout_seconds,
                ),
                step_id=step.step_id,
                idempotency_key=f"{state['value'].turn_id}:{step.step_id}",
            )
            try:
                self._guard.authorize_handoff(
                    current_actor=actor,
                    parent_agent_id=AgentId.ORCHESTRATOR,
                    handoff=handoff,
                    manifest=registered.manifest,
                )
            except AgentPolicyError:
                return self._failure("HANDOFF_POLICY_REJECTED")
            handoffs.append(handoff)
        try:
            results = await asyncio.gather(
                *(self._specialists.run_specialist(handoff) for handoff in handoffs)
            )
        except Exception:
            return self._failure("SPECIALIST_EXECUTION_FAILED")
        if any(
            result.agent_id is not handoff.target_agent_id
            or result.agent_version != handoff.target_agent_version
            for handoff, result in zip(handoffs, results, strict=True)
        ):
            return self._failure("SPECIALIST_RESULT_IDENTITY_MISMATCH")
        return {
            "last_batch_handoffs": tuple(handoffs),
            "last_batch_results": tuple(results),
            "handoffs_used": state["handoffs_used"] + len(handoffs),
            "route": "execute",
        }

    @staticmethod
    def _trusted_specialist_input(
        step: ExecutionStep, value: OrchestratorInput
    ) -> dict[str, JsonValue]:
        """Reconstruct Planning contracts from trusted turn/card context."""
        if step.target_agent_id is not AgentId.PLANNING:
            return step.typed_input
        base: dict[str, JsonValue] = {"locale": value.locale, "brief": value.message}
        if step.capability == "planning.create":
            return {"operation": "CREATE", **base}
        active = value.active_context.active_planning
        if active is None:
            return {"operation": "EXPLAIN", **base}
        references: dict[str, JsonValue] = {
            "workflow_run_id": str(active.workflow_run_id),
            **base,
        }
        if step.capability == "planning.resume":
            return {
                "operation": "RESUME_INPUT",
                **references,
                "manager_instruction": value.message,
            }
        if step.capability == "planning.revise":
            return {
                "operation": "REVISE",
                **references,
                "proposal_id": str(active.proposal_id) if active.proposal_id else None,
                "expected_proposal_version": active.proposal_version,
                "manager_instruction": value.message,
            }
        return {
            "operation": "EXPLAIN",
            **references,
            "proposal_id": str(active.proposal_id) if active.proposal_id else None,
        }

    async def observe_and_update_plan(self, state: OrchestratorState) -> dict[str, object]:
        results = state["last_batch_results"]
        if not results:
            return self._failure("SPECIALIST_EXECUTION_FAILED")
        if any(
            result.status in {AgentRunStatus.FAILED, AgentRunStatus.CANCELLED} for result in results
        ):
            return self._failure("SPECIALIST_RESULT_FAILED")
        completed = (
            *state["completed_step_ids"],
            *(handoff.step_id for handoff in state["last_batch_handoffs"]),
        )
        updates: dict[str, object] = {
            "results": (*state["results"], *results),
            "completed_step_ids": completed,
        }
        awaiting_input = next(
            (result for result in results if result.status is AgentRunStatus.AWAITING_INPUT), None
        )
        if awaiting_input is not None:
            return {**updates, "route": "ask_user"}
        if any(
            result.status is AgentRunStatus.AWAITING_HUMAN
            or any(action.requires_human_gate for action in result.proposed_actions)
            for result in results
        ):
            return {**updates, "route": "human_gate"}
        requested = tuple(
            result.requested_handoff for result in results if result.requested_handoff is not None
        )
        if len(requested) > 1:
            return {**updates, **self._failure("MULTIPLE_HANDOFF_REQUESTS")}
        if requested:
            if state["replans_used"] >= _MAX_REPLANS:
                return {**updates, **self._failure("REPLAN_BUDGET_EXHAUSTED")}
            return {
                **updates,
                "route": "replan",
                "prior_plan": state["plan"],
                "pending_requested_handoff": requested[0],
            }
        return {**updates, "route": "next"}

    async def bounded_repair(self, state: OrchestratorState) -> dict[str, object]:
        if state["pending_requested_handoff"] is not None:
            return {"replans_used": state["replans_used"] + 1}
        return {"repair_attempts": state["repair_attempts"] + 1}

    async def synthesize(self, state: OrchestratorState) -> dict[str, object]:
        plan = state["plan"]
        if plan is None:
            return self._failure("EXECUTION_PLAN_MISSING")
        request = StructuredModelRequest(
            invocation_key=f"orchestrator.{state['value'].locale}.synthesize",
            messages=build_synthesis_messages(state["value"], plan, state["results"]),
            output_schema=OrchestratorSynthesis,
            timeout_seconds=60,
        )
        try:
            response = await self._model_gateway.generate_structured(request)
        except ModelGatewayError:
            return {"route": "manual_fallback", "stop_reason": "MODEL_SYNTHESIS_INVALID"}
        blocks = tuple(
            block
            for block in response.parsed.blocks
            if not isinstance(block, QuestionResponseBlock)
        )
        return {
            "blocks": blocks,
            "model_refs": (*state["model_refs"], response.model_ref),
            "route": "execute",
        }

    async def verify_response(self, state: OrchestratorState) -> dict[str, object]:
        if not state["blocks"]:
            return self._failure("EMPTY_ORCHESTRATOR_RESPONSE")
        return {"status": OrchestratorStatus.COMPLETED, "stop_reason": "COMPLETED"}

    async def ask_user(self, state: OrchestratorState) -> dict[str, object]:
        result = state["last_batch_results"][0]
        question_value = result.typed_output.get("question")
        question = (
            question_value if isinstance(question_value, str) else "Additional input is required."
        )
        return {
            "blocks": (
                QuestionResponseBlock(question=question, response_context={"source": "specialist"}),
            ),
            "status": OrchestratorStatus.AWAITING_INPUT,
            "stop_reason": "AWAITING_INPUT",
        }

    async def human_gate(self, state: OrchestratorState) -> dict[str, object]:
        return {
            "blocks": (
                QuestionResponseBlock(
                    question="Human review is required before continuing.",
                    response_context={"gate": "human_review"},
                ),
            ),
            "status": OrchestratorStatus.AWAITING_HUMAN,
            "stop_reason": "AWAITING_HUMAN",
        }

    async def capability_unavailable(self, state: OrchestratorState) -> dict[str, object]:
        plan = state["plan"]
        if plan is None:
            return self._failure("EXECUTION_PLAN_MISSING")
        blocks = tuple(
            CapabilityUnavailableResponseBlock(
                capability=capability,
                message_key="ai.capability.unavailable",
            )
            for capability in plan.unavailable_capabilities
        )
        return {
            "blocks": blocks,
            "status": OrchestratorStatus.COMPLETED,
            "stop_reason": "CAPABILITY_UNAVAILABLE",
        }

    async def manual_fallback(self, state: OrchestratorState) -> dict[str, object]:
        return {
            "blocks": (
                SafeErrorResponseBlock(
                    code="ORCHESTRATOR_MANUAL_FALLBACK",
                    message_key="ai.error.manualFallback",
                ),
            ),
            "status": OrchestratorStatus.FAILED,
            "stop_reason": state["stop_reason"],
        }

    async def persistable_result(self, state: OrchestratorState) -> dict[str, object]:
        return {
            "output": OrchestratorOutput(
                execution_plan=state["plan"],
                agent_results=state["results"],
                blocks=state["blocks"],
                completed_step_ids=state["completed_step_ids"],
                status=state["status"],
                stop_reason=state["stop_reason"],
                replans_used=state["replans_used"],
                model_refs=state["model_refs"],
            )
        }

    @staticmethod
    def _failure(code: str) -> dict[str, object]:
        return {
            "route": "manual_fallback",
            "status": OrchestratorStatus.FAILED,
            "stop_reason": code,
        }
