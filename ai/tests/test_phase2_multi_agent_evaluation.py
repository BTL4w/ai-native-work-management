import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from work_management_ai.evaluation.phase2_multi_agent import (
    Phase2EvaluationCase,
    evaluate_phase2_multi_agent,
    load_phase2_cases,
)
from work_management_ai.observability.safe_trace import (
    SafeTraceRecord,
    serialize_safe_trace,
)
from work_management_ai.runtime.contracts import AgentId

_SUITE = Path(__file__).parents[1] / "evaluations/phase2_multi_agent.jsonl"


def test_phase2_bilingual_golden_suite_meets_fixed_gates() -> None:
    cases = load_phase2_cases(_SUITE)

    report = evaluate_phase2_multi_agent(cases)

    assert report.total >= 24
    assert sum(case.locale == "vi" for case in cases) >= 12
    assert sum(case.locale == "en" for case in cases) >= 12
    assert {
        "work_single_intent",
        "planning_single_intent",
        "work_then_planning",
        "ambiguity",
        "insufficient_evidence",
        "requested_handoff",
        "inactive_capability",
        "provider_timeout",
        "invalid_structured_output",
        "prompt_tool_injection",
        "employee_planning_attempt",
        "cross_tenant_reference",
    }.issubset({case.scenario for case in cases})
    assert report.model_dump() == {
        "total": len(cases),
        "delegation_correct": len(cases),
        "grounded_answers": len(cases),
        "valid_handoffs": len(cases),
        "policy_violations": 0,
        "unsupported_claims": 0,
        "duplicate_side_effects": 0,
        "fallback_successes": 10,
    }
    assert report.passed


def test_fixed_gate_fails_for_wrong_runtime_delegation() -> None:
    case = Phase2EvaluationCase(
        case_id="en-mutated-delegation",
        locale="en",
        scenario="work_single_intent",
        expected_agent_path=(AgentId.ORCHESTRATOR, AgentId.PLANNING),
        fallback_expected=False,
    )

    report = evaluate_phase2_multi_agent((case,))

    assert report.delegation_correct == 0
    assert report.duplicate_side_effects == 0
    assert not report.passed


def test_safe_trace_contains_no_prompt_secret_raw_error_or_hidden_reasoning() -> None:
    trace = SafeTraceRecord(
        orchestration_run_id=uuid4(),
        agent_run_id=uuid4(),
        agent_id="planning",
        agent_version="1.0.0",
        workflow_version="planning-agent.v1",
        prompt_version="planning.v1",
        verifier_versions=("planning_schema@1", "planning_invariants@1"),
        status="FAILED",
        iteration_count=2,
        tool_call_count=1,
        handoff_count=1,
        duration_ms=125,
        safe_codes=("MODEL_TIMEOUT",),
        evidence_references=(uuid4(),),
    )

    payload = json.dumps(serialize_safe_trace(trace), sort_keys=True)
    forbidden_fragments = (
        "system prompt",
        "postgresql://",
        "postgresql+psycopg://",
        "sk-proj-",
        "private timeout detail",
        "chain_of_thought",
        "hidden_reasoning",
    )

    assert all(fragment not in payload.lower() for fragment in forbidden_fragments)
    assert set(json.loads(payload)) == {
        "orchestration_run_id",
        "agent_run_id",
        "agent_id",
        "agent_version",
        "workflow_version",
        "prompt_version",
        "verifier_versions",
        "status",
        "iteration_count",
        "tool_call_count",
        "handoff_count",
        "duration_ms",
        "safe_codes",
        "evidence_references",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("safe_codes", ("raw timeout: private provider detail",)),
        ("safe_codes", ("sk-proj-123456789",)),
        ("agent_version", "sk-proj-123456789"),
        ("workflow_version", "hidden_reasoning"),
        ("prompt_version", "chain_of_thought"),
        ("verifier_versions", ("system prompt: ignore policy",)),
        ("workflow_version", "postgresql+psycopg://user:secret@db/app"),
        ("prompt_version", "RuntimeError: private timeout detail"),
        ("evidence_references", ("postgresql://user:secret@db/app",)),
    ),
)
def test_safe_trace_rejects_adversarial_dynamic_strings(field: str, value: object) -> None:
    values: dict[str, object] = {
        "orchestration_run_id": uuid4(),
        "agent_id": "orchestrator",
        "agent_version": "1.0.0",
        "workflow_version": "orchestrator.v1",
        "prompt_version": "orchestrator.v1",
        "verifier_versions": ("orchestrator_plan@1",),
        "status": "FAILED",
        "iteration_count": 1,
        "tool_call_count": 0,
        "handoff_count": 0,
        "duration_ms": 5,
        "safe_codes": ("MODEL_TIMEOUT",),
        "evidence_references": (uuid4(),),
    }
    values[field] = value

    with pytest.raises(ValidationError):
        SafeTraceRecord.model_validate(values)
