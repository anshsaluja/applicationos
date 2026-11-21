from uuid import uuid4

from app.extraction import extract_requirements


def test_comma_separated_waiver_does_not_hide_independent_obligation():
    requirements = extract_requirements(
        uuid4(),
        "policy.txt",
        "A passport is not required, applicants must submit proof of address. "
        "A cover letter isn't mandatory, reviewers shall verify the signed consent.",
    )
    assert [item.description for item in requirements] == [
        "applicants must submit proof of address.",
        "reviewers shall verify the signed consent.",
    ]
    assert all(item.status.value == "pending" and not item.evidence for item in requirements)


def test_comma_separated_objects_do_not_create_extra_requirements():
    requirements = extract_requirements(
        uuid4(),
        "checklist.txt",
        "You must upload a passport, a photograph, and proof of address.",
    )
    assert [item.description for item in requirements] == [
        "You must upload a passport, a photograph, and proof of address."
    ]


def test_comma_obligation_has_stable_identity_and_no_satisfaction_evidence():
    source = uuid4()
    text = "A passport is not required, you must upload a signed consent form."
    first = extract_requirements(source, "first.txt", text)
    second = extract_requirements(source, "renamed.txt", text)
    assert len(first) == 1
    assert first[0].id == second[0].id
    assert first[0].description == "you must upload a signed consent form."
    assert first[0].evidence == []
