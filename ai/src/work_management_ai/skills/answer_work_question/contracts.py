"""Skill boundary aliases owned by the reusable Work Q&A capability."""

from work_management_ai.agents.work_intelligence.contracts import (
    WorkIntelligenceInput,
    WorkIntelligenceOutput,
)

AnswerWorkQuestionInput = WorkIntelligenceInput
AnswerWorkQuestionOutput = WorkIntelligenceOutput

__all__ = ["AnswerWorkQuestionInput", "AnswerWorkQuestionOutput"]
