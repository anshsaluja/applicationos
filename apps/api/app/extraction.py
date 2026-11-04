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


def extract_requirements(document_id: UUID, filename: str, text: str) -> list[Requirement]:
    """Extract only explicitly stated obligations; return pending review candidates."""
    results: list[Requirement] = []
    seen: set[str] = set()
    for match in SENTENCE.finditer(text):
        excerpt = match.group().strip()
        normalized = " ".join(excerpt.casefold().split()).rstrip(".!?")
        if not excerpt or not CLAUSE.search(excerpt) or normalized in seen:
            continue
        seen.add(normalized)
        # Evidence here proves the *instruction exists*, not that it is satisfied.
        # Requirement evidence stays empty until actual supporting proof is reviewed.
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
