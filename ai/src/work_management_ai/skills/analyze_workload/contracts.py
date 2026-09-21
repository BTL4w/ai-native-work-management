"""Skill boundary aliases for verified workload analysis."""

from work_management_ai.agents.assignment.contracts import (
    AssignmentAgentInput,
    AssignmentAgentOutput,
)

AnalyzeWorkloadInput = AssignmentAgentInput
AnalyzeWorkloadOutput = AssignmentAgentOutput

__all__ = ["AnalyzeWorkloadInput", "AnalyzeWorkloadOutput"]
