from uuid import uuid4

from app.domain.evaluator import evaluate_requirements
from app.domain.models import Evidence, Requirement, RequirementStatus


def evidence(label: str, excerpt: str) -> Evidence:
    return Evidence(source_document_id=uuid4(), source_label=label, excerpt=excerpt)


def test_requirement_without_evidence_is_missing() -> None:
    requirement = Requirement(title="Identity", description="Provide identity evidence")
    result = evaluate_requirements([requirement])
    assert result.requirements[0].status == RequirementStatus.MISSING
    assert result.missing_count == 1


def test_requirement_with_evidence_is_satisfied() -> None:
    requirement = Requirement(
        title="Income", description="Provide income", evidence=[evidence("income", "$80,000")]
    )
    result = evaluate_requirements([requirement])
    assert result.requirements[0].status == RequirementStatus.SATISFIED


def test_conflicting_evidence_is_inconsistent() -> None:
    requirement = Requirement(
        title="Income",
        description="Provide income",
        evidence=[evidence("income", "$80,000"), evidence("income", "$95,000")],
    )
    result = evaluate_requirements([requirement])
    assert result.requirements[0].status == RequirementStatus.INCONSISTENT
    assert result.inconsistent_count == 1


def test_unsatisfied_dependency_blocks_requirement() -> None:
    parent = Requirement(title="Identity", description="Provide identity")
    child = Requirement(
        title="Background check", description="Authorize check", depends_on=[parent.id]
    )
    result = evaluate_requirements([parent, child])
    assert result.requirements[1].status == RequirementStatus.BLOCKED
