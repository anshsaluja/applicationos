"""Production extraction regression for independent passive clauses joined by 'and'."""
from uuid import uuid4

from app.extraction import extract_requirements


def test_passive_requirement_survives_conjoined_waiver():
    document_id = uuid4()
    text = "A passport is not required and proof of address is required."
    first = extract_requirements(document_id, "policy.txt", text)
    replay = extract_requirements(document_id, "renamed.txt", text)
    assert [item.description for item in first] == ["proof of address is required."]
    assert [item.id for item in first] == [item.id for item in replay]
    assert all(item.status.value == "pending" and item.evidence == [] for item in first)


def test_two_conjoined_passive_obligations_remain_distinct():
    requirements = extract_requirements(
        uuid4(),
        "policy.txt",
        "Proof of identity is mandatory and proof of address is required.",
    )
    assert [item.description for item in requirements] == [
        "Proof of identity is mandatory",
        "proof of address is required.",
    ]
    assert len({item.id for item in requirements}) == 2
    assert all(not item.evidence for item in requirements)


def test_document_object_list_not_split():
    requirements = extract_requirements(
        uuid4(),
        "policy.txt",
        "Applicants must upload a passport and a signed declaration.",
    )
    assert len(requirements) == 1
    assert requirements[0].description == (
        "Applicants must upload a passport and a signed declaration."
    )
