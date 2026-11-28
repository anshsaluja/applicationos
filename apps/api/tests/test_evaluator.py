from uuid import uuid4

import pytest

from app.domain.evaluator import evaluate_requirements
from app.domain.models import Evidence, Requirement, RequirementStatus


def evidence(label: str, excerpt: str, document_id=None) -> Evidence:
    return Evidence(source_document_id=document_id or uuid4(), source_label=label, excerpt=excerpt)


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
    document_id = uuid4()
    requirement = Requirement(
        title="Income",
        description="Provide income",
        evidence=[evidence("income", "$80,000", document_id), evidence("income", "$95,000", document_id)],
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


def test_dependency_uses_recomputed_status_not_stale_input() -> None:
    parent = Requirement(
        title="Identity", description="ID", status=RequirementStatus.SATISFIED
    )
    child = Requirement(
        title="Review", description="Review", evidence=[evidence("review", "approved")],
        depends_on=[parent.id],
    )
    result = evaluate_requirements([child, parent])
    assert [r.status for r in result.requirements] == [
        RequirementStatus.BLOCKED, RequirementStatus.MISSING
    ]


def test_satisfied_dependency_chain_is_order_independent() -> None:
    root = Requirement(title="ID", description="ID", evidence=[evidence("id", "valid")])
    middle = Requirement(
        title="Check", description="Check", depends_on=[root.id],
        evidence=[evidence("check", "complete")],
    )
    leaf = Requirement(
        title="Submit", description="Submit", depends_on=[middle.id],
        evidence=[evidence("submission", "complete")],
    )
    result = evaluate_requirements([leaf, middle, root])
    assert all(r.status == RequirementStatus.SATISFIED for r in result.requirements)


def test_cyclic_dependencies_fail_closed() -> None:
    first = Requirement(title="First", description="First", evidence=[evidence("a", "yes")])
    second = Requirement(
        title="Second", description="Second", evidence=[evidence("b", "yes")],
        depends_on=[first.id],
    )
    first.depends_on = [second.id]
    result = evaluate_requirements([first, second])
    assert all(r.status == RequirementStatus.BLOCKED for r in result.requirements)


def test_unknown_dependency_blocks_even_with_evidence() -> None:
    requirement = Requirement(
        title="Check", description="Check", evidence=[evidence("check", "done")],
        depends_on=[uuid4()],
    )
    result = evaluate_requirements([requirement])
    assert result.requirements[0].status == RequirementStatus.BLOCKED


def test_duplicate_requirement_identity_fails_closed() -> None:
    original = Requirement(
        title="Identity", description="Identity", evidence=[evidence("id", "valid")]
    )
    conflicting = Requirement(
        id=original.id, title="Conflicting identity", description="No evidence"
    )
    with pytest.raises(ValueError, match="Duplicate requirement identifiers"):
        evaluate_requirements([original, conflicting])
    with pytest.raises(ValueError, match="Duplicate requirement identifiers"):
        evaluate_requirements([conflicting, original])


def test_same_label_in_distinct_documents_does_not_imply_conflict() -> None:
    requirement = Requirement(
        title="Income",
        description="Provide income",
        evidence=[evidence("income", "$80,000"), evidence("income", "$95,000")],
    )
    result = evaluate_requirements([requirement])
    assert result.requirements[0].status == RequirementStatus.SATISFIED
    assert result.inconsistent_count == 0


def test_source_label_whitespace_is_normalized_for_conflict_detection() -> None:
    document_id = uuid4()
    requirement = Requirement(
        title="Income",
        description="Provide income",
        evidence=[evidence("Income  Statement", "$80,000", document_id),
                  evidence(" income statement ", "$95,000", document_id)],
    )
    result = evaluate_requirements([requirement])
    assert result.requirements[0].status == RequirementStatus.INCONSISTENT
