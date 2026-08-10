import importlib
import json
import sys
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import pytest
from _pytest.monkeypatch import MonkeyPatch

from work_management_ai.agents.orchestrator.contracts import (
    ActiveConversationContext,
    ExecutionPlan,
    OrchestratorInput,
    OrchestratorStatus,
)
from work_management_ai.agents.orchestrator.evaluators.plan import (
    ExecutionPlanError,
    ready_batches,
    validate_execution_plan,
)
from work_management_ai.agents.orchestrator.harness import OrchestratorHarness
from work_management_ai.model_gateway.mock import MockModelGateway
from work_management_ai.runtime.agent_registry import AgentRegistry
from work_management_ai.runtime.contracts import (
    ActorReference,
    AgentHandoff,
    AgentId,
    AgentResult,
    AgentRunStatus,
    CapabilityUnavailableResponseBlock,
    RequestedHandoff,
    ResolvedActorContext,
    SafeErrorResponseBlock,
)
from work_management_ai.runtime.manifests import AgentManifest, load_yaml_resource
from work_management_ai.runtime.policy_guard import PolicyGuard
from work_management_ai.runtime.skill_registry import SkillRegistry
from work_management_ai.runtime.tool_registry import ToolRegistry


class StaticActorResolver:
    def __init__(self, actor: ResolvedActorContext) -> None:
        self._actor = actor

    async def resolve(self, reference: ActorReference) -> ResolvedActorContext:
        assert reference.membership_id == self._actor.membership_id
        assert reference.organization_id == self._actor.organization_id
        return self._actor


class RecordingSpecialistRunner:
    def __init__(self, results: dict[str, list[AgentResult]] | None = None) -> None:
        self.handoffs: list[AgentHandoff] = []
        self._results = {key: list(values) for key, values in (results or {}).items()}

    async def run_specialist(self, handoff: AgentHandoff) -> AgentResult:
        self.handoffs.append(handoff)
        queued = self._results.get(handoff.capability)
        if queued:
            return queued.pop(0)
        return _completed_result(handoff.target_agent_id)


def _resolved_actor(
    role: Literal["ADMIN", "MANAGER", "EMPLOYEE"] = "MANAGER",
) -> ResolvedActorContext:
    return ResolvedActorContext(
        membership_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        is_active=True,
    )


def _input(
    actor: ResolvedActorContext,
    *,
    locale: Literal["vi", "en"],
    message: str,
) -> OrchestratorInput:
    return OrchestratorInput(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        message=message,
        locale=locale,
        actor=ActorReference(
            membership_id=actor.membership_id,
            organization_id=actor.organization_id,
        ),
        active_context=ActiveConversationContext(recent_messages=()),
    )


def _completed_result(agent_id: AgentId) -> AgentResult:
    return AgentResult(
        agent_id=agent_id,
        agent_version="1.0.0",
        status=AgentRunStatus.COMPLETED,
        typed_output={"summary": "verified result"},
        stop_reason="completed",
    )


def _requested_result(agent_id: AgentId, capability: str) -> AgentResult:
    return AgentResult(
        agent_id=agent_id,
        agent_version="1.0.0",
        status=AgentRunStatus.COMPLETED,
        typed_output={"summary": "needs another capability"},
        requested_handoff=RequestedHandoff(
            target_capability=capability,
            objective=f"Delegate {capability}",
            typed_input={"source": "specialist_result"},
        ),
        stop_reason="requested_handoff",
    )


def _fixture(name: str) -> dict[str, object]:
    path = Path(__file__).parents[5] / "tests" / "fixtures" / name
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _write_specialist_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    package_name: str,
    agent_id: AgentId,
    capability: str,
    roles: tuple[str, ...],
    risk: str,
) -> tuple[str, str]:
    package = tmp_path / package_name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    roles_yaml = ", ".join(roles)
    writes = "NEVER" if risk == "READ_ONLY" else "ALWAYS"
    (package / "agent.yaml").write_text(
        f"""schema_version: "1.0"
agent:
  id: {agent_id.value}
  name: Test {agent_id.value}
  version: "1.0.0"
  owner: test
  activation_phase: 2
capabilities: [{capability}]
contracts:
  input: work_management_ai.runtime.contracts.AgentHandoff
  output: work_management_ai.runtime.contracts.AgentResult
  handoff: work_management_ai.runtime.contracts.AgentHandoff
permissions:
  roles: [{roles_yaml}]
  tenant_scope: actor_membership
  risk_ceiling: {risk}
runtime:
  workflow: {agent_id.value}.v1
  max_iterations: 8
  max_tool_calls: 12
  max_handoffs: 0
  max_replans: 1
  timeout_seconds: 120
  checkpoint: durable
  model_policy: structured_reasoning
allowed_skills: []
allowed_tools: []
approval:
  produced_writes: {writes}
  can_self_approve: false
fallback:
  strategy: SAFE_FAILURE
evaluators: [{agent_id.value}_evaluator@1]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    importlib.invalidate_caches()
    sys.modules.pop(package_name, None)
    return package_name, "agent.yaml"


def _registry(tmp_path: Path, monkeypatch: MonkeyPatch) -> AgentRegistry:
    registry = AgentRegistry(
        skill_registry=SkillRegistry(),
        tool_registry=ToolRegistry(),
        evaluator_ids=frozenset(
            {
                "orchestrator_plan@1",
                "work_intelligence_evaluator@1",
                "planning_evaluator@1",
            }
        ),
    )
    registry.register_resource("work_management_ai.agents.orchestrator", "agent.yaml")
    work_package = _write_specialist_manifest(
        tmp_path,
        monkeypatch,
        package_name="test_work_intelligence_agent",
        agent_id=AgentId.WORK_INTELLIGENCE,
        capability="work.read_project",
        roles=("ADMIN", "MANAGER", "EMPLOYEE"),
        risk="READ_ONLY",
    )
    planning_package = _write_specialist_manifest(
        tmp_path,
        monkeypatch,
        package_name="test_planning_agent",
        agent_id=AgentId.PLANNING,
        capability="planning.create",
        roles=("ADMIN", "MANAGER"),
        risk="PROPOSAL_ONLY",
    )
    registry.register_resource(*work_package)
    registry.register_resource(*planning_package)
    return registry


def _harness(
    *,
    actor: ResolvedActorContext,
    registry: AgentRegistry,
    runner: RecordingSpecialistRunner,
    fixtures: dict[str, object],
) -> OrchestratorHarness:
    return OrchestratorHarness(
        model_gateway=MockModelGateway(fixtures=fixtures, model_ref="mock:orchestrator-v1"),
        registry=registry,
        policy_guard=PolicyGuard(),
        actor_resolver=StaticActorResolver(actor),
        specialists=runner,
    )


def test_orchestrator_manifest_has_zero_business_tools() -> None:
    manifest = load_yaml_resource(
        "work_management_ai.agents.orchestrator", "agent.yaml", AgentManifest
    )

    assert manifest.agent.id is AgentId.ORCHESTRATOR
    assert manifest.agent.version == "1.0.0"
    assert manifest.allowed_tools == ()
    assert manifest.allowed_skills == ()
    assert manifest.runtime.max_tool_calls == 0
    assert manifest.runtime.max_handoffs == 6
    assert manifest.runtime.max_replans == 2


@pytest.mark.asyncio
async def test_single_work_intent_delegates_once(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    golden = _fixture("orchestrator_vi.json")
    actor = _resolved_actor(role="EMPLOYEE")
    runner = RecordingSpecialistRunner()
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={
            "orchestrator.vi.plan": golden["plan"],
            "orchestrator.vi.synthesize": golden["synthesis"],
        },
    )

    output = await harness.run_turn(
        _input(actor, locale="vi", message=cast(str, golden["message"]))
    )

    assert output.status is OrchestratorStatus.COMPLETED
    assert [handoff.target_agent_id for handoff in runner.handoffs] == [AgentId.WORK_INTELLIGENCE]
    assert [block.kind for block in output.blocks] == ["text"]
    assert output.model_refs == ("mock:orchestrator-v1", "mock:orchestrator-v1")


@pytest.mark.asyncio
async def test_manager_multi_intent_runs_work_then_planning(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    golden = _fixture("orchestrator_en.json")
    actor = _resolved_actor()
    runner = RecordingSpecialistRunner()
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={
            "orchestrator.en.plan": golden["plan"],
            "orchestrator.en.synthesize": golden["synthesis"],
        },
    )

    output = await harness.run_turn(
        _input(actor, locale="en", message=cast(str, golden["message"]))
    )

    assert output.status is OrchestratorStatus.COMPLETED
    assert [handoff.target_agent_id for handoff in runner.handoffs] == [
        AgentId.WORK_INTELLIGENCE,
        AgentId.PLANNING,
    ]
    assert output.completed_step_ids == ("read_project", "plan_project")


def test_independent_read_steps_form_one_parallel_batch() -> None:
    plan = ExecutionPlan.model_validate(
        {
            "objectives": ["Read two permitted resources"],
            "steps": [
                {
                    "step_id": "read_project",
                    "target_agent_id": "work_intelligence",
                    "target_agent_version": "1.0.0",
                    "capability": "work.read_project",
                    "objective": "Read Project A",
                    "typed_input": {"reference": "Project A"},
                    "mode": "READ_ONLY",
                },
                {
                    "step_id": "read_project_b",
                    "target_agent_id": "work_intelligence",
                    "target_agent_version": "1.0.0",
                    "capability": "work.read_project",
                    "objective": "Read Project B",
                    "typed_input": {"reference": "Project B"},
                    "mode": "READ_ONLY",
                },
            ],
            "response_language": "en",
        }
    )

    assert tuple(step.step_id for step in ready_batches(plan, frozenset())[0]) == (
        "read_project",
        "read_project_b",
    )


def test_proposal_step_never_runs_in_parallel() -> None:
    plan = ExecutionPlan.model_validate(
        {
            "objectives": ["Read and propose"],
            "steps": [
                {
                    "step_id": "read_project",
                    "target_agent_id": "work_intelligence",
                    "target_agent_version": "1.0.0",
                    "capability": "work.read_project",
                    "objective": "Read Project A",
                    "typed_input": {},
                    "mode": "READ_ONLY",
                },
                {
                    "step_id": "plan_project",
                    "target_agent_id": "planning",
                    "target_agent_version": "1.0.0",
                    "capability": "planning.create",
                    "objective": "Plan Project A",
                    "typed_input": {},
                    "mode": "PROPOSAL",
                },
            ],
            "response_language": "en",
        }
    )

    first = ready_batches(plan, frozenset())[0]
    second = ready_batches(plan, frozenset({"read_project"}))[0]
    assert tuple(step.step_id for step in first) == ("read_project",)
    assert tuple(step.step_id for step in second) == ("plan_project",)


def test_cycle_duplicate_step_and_unknown_agent_are_rejected(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    actor = _resolved_actor()
    registry = _registry(tmp_path, monkeypatch)
    common: dict[str, object] = {
        "target_agent_id": "work_intelligence",
        "target_agent_version": "1.0.0",
        "capability": "work.read_project",
        "objective": "Read",
        "typed_input": {},
        "mode": "READ_ONLY",
    }
    invalid_plans = (
        ExecutionPlan.model_validate(
            {
                "objectives": ["cycle"],
                "steps": [
                    {**common, "step_id": "a", "depends_on": ["b"]},
                    {**common, "step_id": "b", "depends_on": ["a"]},
                ],
                "response_language": "en",
            }
        ),
        ExecutionPlan.model_validate(
            {
                "objectives": ["duplicate"],
                "steps": [
                    {**common, "step_id": "same"},
                    {**common, "step_id": "same"},
                ],
                "response_language": "en",
            }
        ),
        ExecutionPlan.model_validate(
            {
                "objectives": ["unknown"],
                "steps": [
                    {
                        **common,
                        "step_id": "unknown",
                        "target_agent_id": "planning",
                        "target_agent_version": "9.0.0",
                        "capability": "planning.create",
                        "mode": "PROPOSAL",
                    }
                ],
                "response_language": "en",
            }
        ),
    )

    for plan in invalid_plans:
        with pytest.raises(ExecutionPlanError):
            validate_execution_plan(plan, registry, actor)


@pytest.mark.asyncio
async def test_requested_handoff_returns_to_orchestrator_before_new_delegation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    actor = _resolved_actor()
    initial: dict[str, object] = {
        "schema_version": "1.0",
        "objectives": ["Create a grounded Project A proposal"],
        "steps": [
            {
                "step_id": "read_project",
                "target_agent_id": "work_intelligence",
                "target_agent_version": "1.0.0",
                "capability": "work.read_project",
                "objective": "Load permitted Project facts",
                "typed_input": {"reference": "Project A"},
                "depends_on": [],
                "mode": "READ_ONLY",
            }
        ],
        "unavailable_capabilities": [],
        "response_language": "vi",
    }
    replan: dict[str, object] = {
        **initial,
        "steps": [
            *cast(list[object], initial["steps"]),
            {
                "step_id": "plan_project",
                "target_agent_id": "planning",
                "target_agent_version": "1.0.0",
                "capability": "planning.create",
                "objective": "Create a proposal from the evidence",
                "typed_input": {"brief": "Plan Project A"},
                "depends_on": ["read_project"],
                "mode": "PROPOSAL",
            },
        ],
    }
    runner = RecordingSpecialistRunner(
        {"work.read_project": [_requested_result(AgentId.WORK_INTELLIGENCE, "planning.create")]}
    )
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={
            "orchestrator.vi.plan": initial,
            "orchestrator.vi.replan.1": replan,
            "orchestrator.vi.synthesize": {
                "blocks": [{"kind": "text", "text": "Kế hoạch đã sẵn sàng."}]
            },
        },
    )

    output = await harness.run_turn(_input(actor, locale="vi", message="Lập kế hoạch Project A"))

    assert output.replans_used == 1
    assert [handoff.target_agent_id for handoff in runner.handoffs] == [
        AgentId.WORK_INTELLIGENCE,
        AgentId.PLANNING,
    ]
    assert runner.handoffs[1].parent_agent_run_id == runner.handoffs[0].parent_agent_run_id


@pytest.mark.asyncio
async def test_inactive_capability_yields_availability_block_and_zero_handoffs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    actor = _resolved_actor()
    runner = RecordingSpecialistRunner()
    plan = {
        "schema_version": "1.0",
        "objectives": ["Generate a management report"],
        "steps": [],
        "unavailable_capabilities": ["reporting.generate"],
        "response_language": "en",
    }
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={"orchestrator.en.plan": plan},
    )

    output = await harness.run_turn(
        _input(actor, locale="en", message="Generate a weekly management report")
    )

    assert runner.handoffs == []
    assert output.status is OrchestratorStatus.COMPLETED
    assert [block.kind for block in output.blocks] == ["capability_unavailable"]
    block = output.blocks[0]
    assert isinstance(block, CapabilityUnavailableResponseBlock)
    assert block.capability == "reporting.generate"


@pytest.mark.asyncio
async def test_malformed_model_plan_uses_safe_manual_fallback(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    actor = _resolved_actor()
    runner = RecordingSpecialistRunner()
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={
            "orchestrator.vi.plan": {"steps": "invalid"},
            "orchestrator.vi.repair": {"steps": "still invalid"},
        },
    )

    output = await harness.run_turn(_input(actor, locale="vi", message="Giúp tôi lập kế hoạch"))

    assert runner.handoffs == []
    assert output.status is OrchestratorStatus.FAILED
    assert output.stop_reason == "MODEL_PLAN_INVALID"
    assert [block.kind for block in output.blocks] == ["safe_error"]
    block = output.blocks[0]
    assert isinstance(block, SafeErrorResponseBlock)
    assert block.code == "ORCHESTRATOR_MANUAL_FALLBACK"


@pytest.mark.asyncio
async def test_inactive_actor_stops_before_model_or_delegation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    actor = _resolved_actor().model_copy(update={"is_active": False})
    runner = RecordingSpecialistRunner()
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={
            "orchestrator.en.plan": _fixture("orchestrator_en.json")["plan"],
        },
    )

    output = await harness.run_turn(
        _input(actor, locale="en", message="Show the current project status")
    )

    assert output.status is OrchestratorStatus.FAILED
    assert output.stop_reason == "ACTOR_INACTIVE"
    assert output.execution_plan is None
    assert output.model_refs == ()
    assert runner.handoffs == []


@pytest.mark.asyncio
async def test_invalid_replan_never_reexecutes_the_prior_plan(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    actor = _resolved_actor()
    initial: dict[str, object] = {
        "schema_version": "1.0",
        "objectives": ["Create a grounded Project A proposal"],
        "steps": [
            {
                "step_id": "read_project",
                "target_agent_id": "work_intelligence",
                "target_agent_version": "1.0.0",
                "capability": "work.read_project",
                "objective": "Read Project A",
                "typed_input": {},
                "mode": "READ_ONLY",
            }
        ],
        "response_language": "en",
    }
    runner = RecordingSpecialistRunner(
        {"work.read_project": [_requested_result(AgentId.WORK_INTELLIGENCE, "planning.create")]}
    )
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={
            "orchestrator.en.plan": initial,
            "orchestrator.en.replan.1": {"steps": "invalid"},
        },
    )

    output = await harness.run_turn(
        _input(actor, locale="en", message="Create a grounded Project A proposal")
    )

    assert output.status is OrchestratorStatus.FAILED
    assert output.stop_reason == "MODEL_PLAN_INVALID"
    assert output.execution_plan is None
    assert [handoff.capability for handoff in runner.handoffs] == ["work.read_project"]


@pytest.mark.asyncio
async def test_replan_budget_exhaustion_stops_without_broadening_scope(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    actor = _resolved_actor()
    runner = RecordingSpecialistRunner(
        {
            "work.read_project": [_requested_result(AgentId.WORK_INTELLIGENCE, "planning.create")],
            "planning.create": [
                _requested_result(AgentId.PLANNING, "planning.create"),
                _requested_result(AgentId.PLANNING, "planning.create"),
            ],
        }
    )
    initial: dict[str, object] = {
        "schema_version": "1.0",
        "objectives": ["Create a grounded Project A proposal"],
        "steps": [
            {
                "step_id": "read_project",
                "target_agent_id": "work_intelligence",
                "target_agent_version": "1.0.0",
                "capability": "work.read_project",
                "objective": "Read Project A",
                "typed_input": {},
                "mode": "READ_ONLY",
            }
        ],
        "response_language": "en",
    }
    replan_one: dict[str, object] = {
        **initial,
        "steps": [
            *cast(list[object], initial["steps"]),
            {
                "step_id": "plan_one",
                "target_agent_id": "planning",
                "target_agent_version": "1.0.0",
                "capability": "planning.create",
                "objective": "Create proposal",
                "typed_input": {},
                "depends_on": ["read_project"],
                "mode": "PROPOSAL",
            },
        ],
    }
    replan_two: dict[str, object] = {
        **replan_one,
        "steps": [
            *cast(list[object], replan_one["steps"]),
            {
                "step_id": "plan_two",
                "target_agent_id": "planning",
                "target_agent_version": "1.0.0",
                "capability": "planning.create",
                "objective": "Retry within approved scope",
                "typed_input": {},
                "depends_on": ["plan_one"],
                "mode": "PROPOSAL",
            },
        ],
    }
    harness = _harness(
        actor=actor,
        registry=_registry(tmp_path, monkeypatch),
        runner=runner,
        fixtures={
            "orchestrator.en.plan": initial,
            "orchestrator.en.replan.1": replan_one,
            "orchestrator.en.replan.2": replan_two,
        },
    )

    output = await harness.run_turn(
        _input(actor, locale="en", message="Create a grounded Project A proposal")
    )

    assert output.status is OrchestratorStatus.FAILED
    assert output.stop_reason == "REPLAN_BUDGET_EXHAUSTED"
    assert output.replans_used == 2
    assert [handoff.capability for handoff in runner.handoffs] == [
        "work.read_project",
        "planning.create",
        "planning.create",
    ]
    assert output.blocks[0].kind == "safe_error"
