"""Conservative, auditable extraction of explicit requirement statements.

This baseline does not invent requirements or treat instructions as proof of compliance.
Every result retains an exact excerpt and the source document identifier.
"""
from __future__ import annotations

import re
from uuid import UUID, uuid5

from .domain.models import Evidence, Requirement

CLAUSE = re.compile(
    r"\b(?:must|shall|required|need to|needs to|provide|submit|upload|include)\b",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]|$)")


# Explicit waivers are not requirements. Keep this conservative: ambiguous
# clauses still become pending review candidates rather than being inferred.
WAIVER = re.compile(
    r"\b(?:not\s+required\s+to|not\s+necessary\s+to|"
    r"(?:do|does)\s+not\s+need\s+to|no\s+need\s+to|need\s+not)\b",
    re.IGNORECASE,
)


def extract_requirements(document_id: UUID, filename: str, text: str) -> list[Requirement]:
    """Extract only explicitly stated obligations; return pending review candidates."""
    results: list[Requirement] = []
    seen: set[str] = set()
    for match in SENTENCE.finditer(text):
        sentence = match.group().strip()
        for clause in CONTRAST.split(sentence):
            excerpt = clause.strip()
            normalized = " ".join(excerpt.casefold().split()).rstrip(".!?")
            if not excerpt or not CLAUSE.search(excerpt) or WAIVER.search(excerpt) or normalized in seen:
                continue
            seen.add(normalized)
            # Provenance is the exact extracted clause, not satisfaction evidence.
            results.append(
                Requirement(
                    id=uuid5(document_id, normalized),
                    title=excerpt[:120],
                    description=excerpt,
                    evidence=[],
                )
            )
    return results


def instruction_provenance(document_id: UUID, filename: str, excerpt: str) -> Evidence:
    """Source of the instruction; never pass this as satisfaction evidence."""
    return Evidence(source_document_id=document_id, source_label=filename, excerpt=excerpt)
