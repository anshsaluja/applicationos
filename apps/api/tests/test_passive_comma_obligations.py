from uuid import uuid4

from app.extraction import extract_requirements


def test_passive_required_clause_survives_comma_waiver():
    requirements = extract_requirements(
        uuid4(),
        "policy.txt",
        "A passport is not required, proof of address is required.",
    )
    assert [item.description for item in requirements] == ["proof of address is required."]
    assert all(item.status.value == "pending" and item.evidence == [] for item in requirements)


def test_passive_mandatory_and_compulsory_clauses():
    requirements = extract_requirements(
        uuid4(),
        "policy.txt",
        "A cover letter isn't mandatory, signed consent is mandatory. "
        "A passport is not required, identity verification is compulsory.",
    )
    assert [item.description for item in requirements] == [
        "signed consent is mandatory.",
        "identity verification is compulsory.",
    ]


def test_object_list_stays_one_requirement():
    requirements = extract_requirements(
        uuid4(),
        "policy.txt",
        "A passport, a photograph, and proof of address are required.",
    )
    assert len(requirements) == 1
    assert requirements[0].description == (
        "A passport, a photograph, and proof of address are required."
    )
