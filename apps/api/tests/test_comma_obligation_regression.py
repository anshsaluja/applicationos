"""Regression coverage for comma-separated policy obligations.

These examples exercise the production extractor, not a standalone regex copy.
"""
from uuid import uuid4

from app.extraction import extract_requirements


def test_comma_waiver_keeps_independent_active_and_passive_obligations():
    source = uuid4()
    text = (
        "A passport is not required, proof of address is required. "
        "You do not need to submit a photograph, applicants must sign the declaration."
    )
    first = extract_requirements(source, "policy.txt", text)
    replay = extract_requirements(source, "renamed-policy.txt", text)
    assert [item.description for item in first] == [
        "proof of address is required.",
        "applicants must sign the declaration.",
    ]
    assert [item.id for item in first] == [item.id for item in replay]
    assert all(item.status.value == "pending" and item.evidence == [] for item in first)


def test_comma_delimited_document_objects_stay_one_requirement():
    items = extract_requirements(
        uuid4(),
        "documents.txt",
        "Applicants must provide a passport, proof of address, and a signed declaration.",
    )
    assert [item.description for item in items] == [
        "Applicants must provide a passport, proof of address, and a signed declaration."
    ]
    assert items[0].evidence == []


def test_comma_waiver_followed_by_reviewer_obligation():
    items = extract_requirements(
        uuid4(),
        "review.txt",
        "A second photo is not mandatory, the reviewer shall verify the consent form.",
    )
    assert [item.description for item in items] == [
        "the reviewer shall verify the consent form."
    ]
    assert items[0].status.value == "pending"
