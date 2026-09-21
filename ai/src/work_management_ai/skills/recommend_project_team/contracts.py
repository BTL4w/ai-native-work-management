"""Skill boundary aliases for team recommendation and revision."""

from work_management_ai.agents.assignment.contracts import (
    AssignmentAgentInput,
    AssignmentAgentOutput,
)

RecommendProjectTeamInput = AssignmentAgentInput
RecommendProjectTeamOutput = AssignmentAgentOutput

__all__ = ["RecommendProjectTeamInput", "RecommendProjectTeamOutput"]
