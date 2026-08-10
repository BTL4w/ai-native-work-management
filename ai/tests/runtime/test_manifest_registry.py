import importlib
import sys
from pathlib import Path
from typing import cast

import pytest
import yaml
from _pytest.monkeypatch import MonkeyPatch
from pydantic import ValidationError

from work_management_ai.runtime.agent_registry import (
    AgentRegistry,
    AgentRegistryError,
)
from work_management_ai.runtime.contracts import AgentId, RiskLevel
from work_management_ai.runtime.manifests import (
    AgentManifest,
    SkillManifest,
    ToolManifest,
    canonical_manifest_fingerprint,
    load_yaml_resource,
)
from work_management_ai.runtime.skill_registry import SkillRegistry, SkillRegistryError
from work_management_ai.runtime.tool_registry import ToolRegistry, ToolRegistryError


def _agent_manifest_yaml(
    *,
    version: str = "1.0.0",
    activation_phase: int = 2,
    input_contract: str = "work_management_ai.runtime.contracts.AgentHandoff",
    skills: str = "  - create_project_plan@1",
    tools: str = "  - planning.validate_draft@1",
    evaluators: str = "  - planning_schema@1",
) -> str:
    return f'''schema_version: "1.0"
agent:
  id: planning
  name: Planning Agent
  version: "{version}"
  owner: work-planning
  activation_phase: {activation_phase}
capabilities:
  - planning.create
contracts:
  input: {input_contract}
  output: work_management_ai.runtime.contracts.AgentResult
  handoff: work_management_ai.runtime.contracts.AgentHandoff
permissions:
  roles: [ADMIN, MANAGER]
  tenant_scope: actor_membership
  risk_ceiling: PROPOSAL_ONLY
runtime:
  workflow: planning.v1
  max_iterations: 8
  max_tool_calls: 12
  max_handoffs: 0
  max_replans: 1
  timeout_seconds: 120
  checkpoint: durable
  model_policy: structured_reasoning
allowed_skills:
{skills}
allowed_tools:
{tools}
approval:
  produced_writes: ALWAYS
  can_self_approve: false
fallback:
  strategy: MANUAL_EDITABLE_DRAFT
evaluators:
{evaluators}
'''


def _write_resource_package(
    tmp_path: Path, monkeypatch: MonkeyPatch, yaml_text: str
) -> tuple[str, str]:
    package_name = "runtime_manifest_fixture"
    package = tmp_path / package_name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "agent.yaml").write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    importlib.invalidate_caches()
    sys.modules.pop(package_name, None)
    return package_name, "agent.yaml"


def _skill_registry() -> SkillRegistry:
    return SkillRegistry(
        [
            SkillManifest.model_validate(
                {
                    "schema_version": "1.0",
                    "name": "create_project_plan",
                    "version": "1.2.0",
                    "owner": "work-planning",
                    "description": "Create a project proposal",
                    "runnable_by_agents": ["planning"],
                    "allowed_tools": ["planning.validate_draft@1"],
                    "risk_level": "PROPOSAL_ONLY",
                    "input_contract": "work_management_ai.runtime.contracts.AgentHandoff",
                    "output_contract": "work_management_ai.runtime.contracts.AgentResult",
                    "evaluators": ["planning_schema@1"],
                }
            )
        ]
    )


def _tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolManifest.model_validate(
                {
                    "schema_version": "1.0",
                    "name": "planning.validate_draft",
                    "version": "1.4.0",
                    "owner": "work-planning",
                    "tenant_scope": "actor_membership",
                    "risk_level": "PROPOSAL_ONLY",
                    "input_contract": "work_management_ai.runtime.contracts.AgentHandoff",
                    "output_contract": "work_management_ai.runtime.contracts.AgentResult",
                    "timeout_seconds": 30,
                    "max_attempts": 1,
                    "idempotency": "REQUIRED",
                    "audit": "SAFE_METADATA",
                }
            )
        ]
    )


def _registry(
    *,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> AgentRegistry:
    return AgentRegistry(
        skill_registry=skill_registry or _skill_registry(),
        tool_registry=tool_registry or _tool_registry(),
        evaluator_ids=frozenset({"planning_schema@1"}),
    )


def test_registry_loads_exact_packaged_manifest_version(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    package, resource = _write_resource_package(
        tmp_path, monkeypatch, _agent_manifest_yaml(version="1.0.0")
    )
    registry = _registry()

    registered = registry.register_resource(package, resource)
    resolved = registry.resolve(AgentId.PLANNING, "1.0.0", active_phase=2)

    assert resolved == registered
    assert resolved.manifest.agent.version == "1.0.0"
    assert resolved.fingerprint == canonical_manifest_fingerprint(resolved.manifest)
    with pytest.raises(AgentRegistryError, match="AGENT_VERSION_NOT_REGISTERED"):
        registry.resolve(AgentId.PLANNING, "1.0.1", active_phase=2)


def test_registry_rejects_inactive_phase_and_unknown_contract(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    package, resource = _write_resource_package(
        tmp_path, monkeypatch, _agent_manifest_yaml(activation_phase=3)
    )
    registry = _registry()
    registry.register_resource(package, resource)

    with pytest.raises(AgentRegistryError, match="AGENT_PHASE_INACTIVE"):
        registry.resolve(AgentId.PLANNING, "1.0.0", active_phase=2)

    unknown_contract_package, unknown_contract_resource = _write_resource_package(
        tmp_path / "other",
        monkeypatch,
        _agent_manifest_yaml(input_contract="work_management_ai.runtime.contracts.DoesNotExist"),
    )
    with pytest.raises(AgentRegistryError, match="AGENT_CONTRACT_INVALID"):
        _registry().register_resource(unknown_contract_package, unknown_contract_resource)


@pytest.mark.parametrize(
    ("skills", "tools", "evaluators", "code"),
    [
        (
            "  - missing_skill@1",
            "  - planning.validate_draft@1",
            "  - planning_schema@1",
            "AGENT_SKILL_NOT_REGISTERED",
        ),
        (
            "  - create_project_plan@1",
            "  - missing.tool@1",
            "  - planning_schema@1",
            "AGENT_TOOL_NOT_REGISTERED",
        ),
        (
            "  - create_project_plan@1",
            "  - planning.validate_draft@1",
            "  - missing_evaluator@1",
            "AGENT_EVALUATOR_NOT_REGISTERED",
        ),
    ],
)
def test_registry_rejects_missing_skill_tool_and_evaluator(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    skills: str,
    tools: str,
    evaluators: str,
    code: str,
) -> None:
    package, resource = _write_resource_package(
        tmp_path,
        monkeypatch,
        _agent_manifest_yaml(skills=skills, tools=tools, evaluators=evaluators),
    )

    with pytest.raises(AgentRegistryError, match=code):
        _registry().register_resource(package, resource)


def test_manifest_loader_uses_safe_strict_yaml_and_semantic_versions(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    package, resource = _write_resource_package(
        tmp_path,
        monkeypatch,
        _agent_manifest_yaml(version="latest") + "unexpected: true\n",
    )

    with pytest.raises(ValidationError):
        load_yaml_resource(package, resource, AgentManifest)


def test_manifest_loader_rejects_executable_yaml_tags(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    package, resource = _write_resource_package(
        tmp_path,
        monkeypatch,
        '!!python/object/apply:os.system ["echo unsafe"]',
    )

    with pytest.raises(yaml.YAMLError):
        load_yaml_resource(package, resource, AgentManifest)


def test_skill_and_tool_registries_reject_unknown_contracts() -> None:
    invalid_skill = (
        _skill_registry()
        .resolve("create_project_plan@1")
        .manifest.model_copy(
            update={"input_contract": "work_management_ai.runtime.contracts.DoesNotExist"}
        )
    )
    invalid_tool = (
        _tool_registry()
        .resolve("planning.validate_draft@1")
        .manifest.model_copy(
            update={"output_contract": "work_management_ai.runtime.contracts.DoesNotExist"}
        )
    )

    with pytest.raises(SkillRegistryError, match="SKILL_CONTRACT_INVALID"):
        SkillRegistry([invalid_skill])
    with pytest.raises(ToolRegistryError, match="TOOL_CONTRACT_INVALID"):
        ToolRegistry([invalid_tool])


def test_registry_rejects_permission_incompatible_skill_and_tool(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    package, resource = _write_resource_package(tmp_path, monkeypatch, _agent_manifest_yaml())
    skill = _skill_registry().resolve("create_project_plan@1").manifest
    wrong_agent_skill = skill.model_copy(update={"runnable_by_agents": (AgentId.ORCHESTRATOR,)})
    with pytest.raises(AgentRegistryError, match="AGENT_SKILL_PERMISSION_INCOMPATIBLE"):
        _registry(skill_registry=SkillRegistry([wrong_agent_skill])).register_resource(
            package, resource
        )

    read_only_skill = skill.model_copy(update={"risk_level": RiskLevel.READ_ONLY})
    proposal_tool = (
        _tool_registry()
        .resolve("planning.validate_draft@1")
        .manifest.model_copy(update={"risk_level": RiskLevel.PROPOSAL_ONLY})
    )
    read_only_manifest = (
        _agent_manifest_yaml()
        .replace("risk_ceiling: PROPOSAL_ONLY", "risk_ceiling: READ_ONLY")
        .replace("produced_writes: ALWAYS", "produced_writes: NEVER")
    )
    read_only_package, read_only_resource = _write_resource_package(
        tmp_path / "read_only", monkeypatch, read_only_manifest
    )
    with pytest.raises(AgentRegistryError, match="AGENT_TOOL_RISK_INCOMPATIBLE"):
        _registry(
            skill_registry=SkillRegistry([read_only_skill]),
            tool_registry=ToolRegistry([proposal_tool]),
        ).register_resource(read_only_package, read_only_resource)


def test_registry_rejects_agent_roles_outside_tool_role_allowlist(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    package, resource = _write_resource_package(tmp_path, monkeypatch, _agent_manifest_yaml())
    employee_only_tool = (
        _tool_registry()
        .resolve("planning.validate_draft@1")
        .manifest.model_copy(update={"roles": ("EMPLOYEE",)})
    )

    with pytest.raises(AgentRegistryError, match="AGENT_TOOL_ROLE_INCOMPATIBLE"):
        _registry(tool_registry=ToolRegistry([employee_only_tool])).register_resource(
            package, resource
        )


def test_contract_paths_cannot_import_outside_work_management_ai() -> None:
    with pytest.raises(ValidationError):
        AgentManifest.model_validate(
            {
                **_registry_manifest_dict(),
                "contracts": {
                    "input": "os.system",
                    "output": "work_management_ai.runtime.contracts.AgentResult",
                    "handoff": "work_management_ai.runtime.contracts.AgentHandoff",
                },
            }
        )


def test_manifest_rejects_an_empty_role_allowlist() -> None:
    values = _registry_manifest_dict()
    permissions = cast(dict[str, object], values["permissions"])
    permissions["roles"] = []

    with pytest.raises(ValidationError):
        AgentManifest.model_validate(values)


def test_skill_and_tool_manifests_preserve_runtime_governance_metadata() -> None:
    skill = SkillManifest.model_validate(
        {
            "schema_version": "1.0",
            "name": "answer_work_question",
            "version": "1.0.0",
            "owner": "work-intelligence",
            "description": "Answer permission-safe work questions",
            "runnable_by_agents": ["work_intelligence"],
            "allowed_tools": ["work.read_my_tasks@1"],
            "risk_level": "READ_ONLY",
            "input_contract": "work_management_ai.runtime.contracts.AgentHandoff",
            "output_contract": "work_management_ai.runtime.contracts.AgentResult",
            "evaluators": ["work_grounding@1"],
            "triggers": ["vi:task của tôi", "en:my tasks"],
            "required_context": ["authenticated_actor", "tenant_scope"],
            "approval": "NONE",
            "stop_conditions": ["ambiguous_resource", "insufficient_evidence"],
        }
    )
    tool = ToolManifest.model_validate(
        {
            "schema_version": "1.0",
            "name": "work.read_my_tasks",
            "version": "1.0.0",
            "owner": "work-intelligence",
            "tenant_scope": "actor_membership",
            "roles": ["ADMIN", "MANAGER", "EMPLOYEE"],
            "risk_level": "READ_ONLY",
            "input_contract": "work_management_ai.runtime.contracts.AgentHandoff",
            "output_contract": "work_management_ai.runtime.contracts.AgentResult",
            "timeout_seconds": 5,
            "max_attempts": 1,
            "retry_policy": "NONE",
            "idempotency": "NOT_APPLICABLE",
            "audit": "SAFE_METADATA",
            "evidence_output": True,
            "freshness_output": True,
            "trace_metadata": ["tool_id", "duration_ms", "result_status"],
        }
    )

    assert skill.approval == "NONE"
    assert skill.triggers == ("vi:task của tôi", "en:my tasks")
    assert tool.roles == ("ADMIN", "MANAGER", "EMPLOYEE")
    assert tool.retry_policy == "NONE"
    assert tool.trace_metadata == ("tool_id", "duration_ms", "result_status")


def test_registry_rejects_read_only_agent_that_declares_writes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    read_only_manifest = _agent_manifest_yaml().replace(
        "risk_ceiling: PROPOSAL_ONLY", "risk_ceiling: READ_ONLY"
    )
    package, resource = _write_resource_package(tmp_path, monkeypatch, read_only_manifest)
    skill = (
        _skill_registry()
        .resolve("create_project_plan@1")
        .manifest.model_copy(update={"risk_level": RiskLevel.READ_ONLY})
    )
    tool = (
        _tool_registry()
        .resolve("planning.validate_draft@1")
        .manifest.model_copy(update={"risk_level": RiskLevel.READ_ONLY})
    )

    with pytest.raises(AgentRegistryError, match="AGENT_WRITE_POLICY_INCOMPATIBLE"):
        _registry(
            skill_registry=SkillRegistry([skill]),
            tool_registry=ToolRegistry([tool]),
        ).register_resource(package, resource)


def _registry_manifest_dict() -> dict[str, object]:
    import yaml

    loaded = yaml.safe_load(_agent_manifest_yaml())
    assert isinstance(loaded, dict)
    return cast(dict[str, object], loaded)
