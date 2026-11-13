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
# Split contrasting instructions so a waiver cannot mask a separate obligation.
CONTRAST = re.compile(r"\s*(?:[,;]\s*)?\b(?:but|however)\b[,]?\s*", re.IGNORECASE)


# Explicit waivers are not requirements. Keep this conservative: ambiguous
# clauses still become pending review candidates rather than being inferred.
# Semicolon-separated clauses can contain independent waivers and obligations.
# Keep each clause separate so an optional item cannot suppress a required one.
CLAUSE_SEPARATOR = re.compile(r"\s*;\s*")
# Split independently stated obligations joined by "and" without splitting
# ordinary object lists such as "upload a passport and a photo".
INDEPENDENT_OBLIGATION = re.compile(
    r"\s+and\s+(?=(?:(?:you|applicants?|users?|the\s+applicant|the\s+user)\s+)?"
    r"(?:must|shall|need(?:s)?\s+to)\b)",
    re.IGNORECASE,
)

WAIVER = re.compile(
    r"\b(?:not\s+required(?:\s+to)?|not\s+necessary(?:\s+to)?|"
    r"(?:do|does)\s+not\s+need\s+to|(?:don[’\x27]t|doesn[’\x27]t)\s+need\s+to|"
    r"no\s+need\s+to|need\s+not)\b",
    re.IGNORECASE,
)


def extract_requirements(document_id: UUID, filename: str, text: str) -> list[Requirement]:
    """Extract only explicitly stated obligations; return pending review candidates."""
    results: list[Requirement] = []
    seen: set[str] = set()
    for match in SENTENCE.finditer(text):
        sentence = match.group().strip()
        for clause in (part for section in CLAUSE_SEPARATOR.split(sentence) for contrast in CONTRAST.split(section) for part in INDEPENDENT_OBLIGATION.split(contrast)):
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
