"""Check the frontend runtime contract against FastAPI's public OpenAPI schema."""

import json
from pathlib import Path
from typing import cast

from app.main import app


def _describe(schema: dict[str, object], schemas: dict[str, object]) -> str:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        name = reference.rsplit("/", 1)[-1]
        target = schemas[name]
        assert isinstance(target, dict)
        return f"enum:{name}" if "enum" in target else f"ref:{name}"

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        fragments = cast(list[dict[str, object]], any_of)
        return "|".join(sorted(_describe(item, schemas) for item in fragments))

    schema_type = schema.get("type")
    if schema_type == "array":
        return f"array:{_describe(schema['items'], schemas)}"  # type: ignore[arg-type]
    if schema_type == "string":
        result = "string"
        if schema.get("format"):
            result += f":{schema['format']}"
        if "minLength" in schema or "maxLength" in schema:
            result += f"[{schema.get('minLength', '')},{schema.get('maxLength', '')}]"
        return result
    if schema_type in {"object", "integer", "number", "boolean", "null"}:
        return str(schema_type)
    raise AssertionError(f"Unsupported OpenAPI schema fragment: {schema}")


def test_frontend_work_contract_manifest_matches_openapi() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "features"
        / "work"
        / "openapi-contract.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schemas = cast(
        dict[str, object],
        app.openapi()["components"]["schemas"],
    )

    assert {
        "GoalCreateRequest",
        "GoalUpdateRequest",
        "GoalResponse",
        "MilestoneCreateRequest",
        "MilestoneUpdateRequest",
        "MilestoneResponse",
        "DependencyCreateRequest",
        "DependencyUpdateRequest",
        "DependencyResponse",
        "AcceptanceCriterionCreateRequest",
        "AcceptanceCriterionUpdateRequest",
        "AcceptanceCriterionResponse",
        "PlanningPageResponse",
        "DeleteResponse",
    }.issubset(manifest["schemas"])

    for enum_name, expected in manifest["enums"].items():
        schema = schemas[enum_name]
        assert isinstance(schema, dict)
        assert schema["enum"] == expected

    for schema_name, expected in manifest["schemas"].items():
        schema = cast(dict[str, object], schemas[schema_name])
        properties = cast(dict[str, dict[str, object]], schema["properties"])
        actual = {
            "required": cast(list[str], schema.get("required", [])),
            "properties": {name: _describe(value, schemas) for name, value in properties.items()},
        }
        assert actual == expected, schema_name
