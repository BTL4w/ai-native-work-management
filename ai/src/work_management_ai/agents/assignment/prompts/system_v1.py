"""Grounded-explanation-only Assignment Agent prompt."""

import json
from typing import Literal

from pydantic import BaseModel

from work_management_ai.model_gateway.contracts import ModelMessage

PROMPT_VERSION = "assignment-agent-system-v1"


def build_explanation_messages(
    snapshot: BaseModel,
    *,
    locale: Literal["vi", "en"],
    skill_instructions: str,
) -> tuple[ModelMessage, ...]:
    payload = {
        "locale": locale,
        "verified_deterministic_snapshot": snapshot.model_dump(mode="json"),
        "skill_instructions": skill_instructions,
    }
    return (
        ModelMessage(
            role="system",
            content=(
                "Explain only the supplied deterministic snapshot in the requested locale. "
                "Copy every ID, name, score, workload value and evidence ID exactly. "
                "Do not infer protected attributes, approval, eligibility, scores, people, "
                "requirements or authority. Return only the requested structured contract."
            ),
        ),
        ModelMessage(role="user", content=json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    )
