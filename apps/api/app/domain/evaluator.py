from __future__ import annotations

from dataclasses import dataclass

from .models import Evidence, Requirement, RequirementStatus


@dataclass(frozen=True)
class EvaluationResult:
    requirements: list[Requirement]
    missing_count: int
    inconsistent_count: int


def evaluate_requirements(requirements: list[Requirement]) -> EvaluationResult:
    """Evaluate requirement state without an LLM.

    Deterministic rules provide a safe baseline and make agent behavior testable.
    Requirements with evidence are satisfied unless their evidence conflicts; requirements
    without evidence are missing. A dependency that is not satisfied blocks its dependents.
    """
    by_id = {requirement.id: requirement for requirement in requirements}
    if len(by_id) != len(requirements):
        # Duplicate identities make dependency resolution ambiguous; never
        # silently select the last record and mark the graph satisfied.
        raise ValueError("Duplicate requirement identifiers in evaluation graph")
    resolved: dict = {}
    visiting: set = set()

    def resolve(requirement_id):
        # Resolve the graph rather than trusting stale, caller-supplied statuses.
        # Missing references and dependency cycles fail closed.
        if requirement_id not in by_id or requirement_id in visiting:
            return RequirementStatus.BLOCKED
        if requirement_id in resolved:
            return resolved[requirement_id]

        requirement = by_id[requirement_id]
        visiting.add(requirement_id)
        dependency_blocked = any(
            resolve(dependency) != RequirementStatus.SATISFIED
            for dependency in requirement.depends_on
        )
        visiting.remove(requirement_id)

        if dependency_blocked:
            status = RequirementStatus.BLOCKED
        elif _has_conflicting_evidence(requirement.evidence):
            status = RequirementStatus.INCONSISTENT
        elif requirement.evidence:
            status = RequirementStatus.SATISFIED
        else:
            status = RequirementStatus.MISSING
        resolved[requirement_id] = status
        return status

    evaluated = [
        requirement.model_copy(update={"status": resolve(requirement.id)})
        for requirement in requirements
    ]

    return EvaluationResult(
        requirements=evaluated,
        missing_count=sum(r.status == RequirementStatus.MISSING for r in evaluated),
        inconsistent_count=sum(r.status == RequirementStatus.INCONSISTENT for r in evaluated),
    )


def _has_conflicting_evidence(evidence: list[Evidence]) -> bool:
    """Flag distinct normalized excerpts for the same source label as conflicting evidence."""
    values_by_label: dict[str, set[str]] = {}
    for item in evidence:
        normalized = " ".join(item.excerpt.casefold().split())
        values_by_label.setdefault(item.source_label.casefold(), set()).add(normalized)
    return any(len(values) > 1 for values in values_by_label.values())
