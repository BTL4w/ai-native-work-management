"""Deterministic evidence and asserted-field verification."""

import re

from work_management_ai.agents.work_intelligence.contracts import WorkIntelligenceOutput


class GroundingError(ValueError):
    pass


_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_STATUS = re.compile(r"\b(?:TO_DO|IN_PROGRESS|DONE)\b")
_COUNT = re.compile(r"(?<![\w-])\d+(?![\w-])")


def verify_grounded_answer(output: WorkIntelligenceOutput) -> None:
    evidence_by_id = {item.evidence_id: item for item in output.evidence}
    if len(evidence_by_id) != len(output.evidence):
        raise GroundingError("DUPLICATE_EVIDENCE_ID")
    for claim in output.claims:
        if any(evidence_id not in evidence_by_id for evidence_id in claim.evidence_ids):
            raise GroundingError("MISSING_CLAIM_EVIDENCE")
        for assertion in claim.assertions:
            if assertion.evidence_id not in claim.evidence_ids:
                raise GroundingError("ASSERTION_OUTSIDE_CLAIM_EVIDENCE")
            evidence = evidence_by_id[assertion.evidence_id]
            if assertion.field not in evidence.fields:
                raise GroundingError("UNSUPPORTED_CLAIM_FIELD")
            if evidence.fields[assertion.field] != assertion.value:
                raise GroundingError("UNSUPPORTED_CLAIM_VALUE")
        asserted = {
            str(assertion.value)
            for assertion in claim.assertions
            if isinstance(assertion.value, str | int | float)
            and not isinstance(assertion.value, bool)
        }
        dates = set(_DATE.findall(claim.text))
        statuses = set(_STATUS.findall(claim.text))
        text_without_dates = _DATE.sub("", claim.text)
        counts = set(_COUNT.findall(text_without_dates))
        if not dates.union(statuses, counts).issubset(asserted):
            raise GroundingError("UNASSERTED_STRUCTURED_FACT")
