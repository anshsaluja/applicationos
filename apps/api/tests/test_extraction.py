from uuid import uuid4

from app.extraction import extract_requirements, instruction_provenance


def test_extracts_only_explicit_obligations_without_claiming_satisfaction():
    document_id = uuid4()
    requirements = extract_requirements(
        document_id,
        "instructions.txt",
        "Welcome to the portal. You must provide proof of income. "
        "Submit a valid ID! This is an informational note.",
    )
    assert len(requirements) == 2
    assert all(not requirement.evidence for requirement in requirements)
    assert all(requirement.status.value == "pending" for requirement in requirements)


def test_deduplicates_repeated_instructions_and_ignores_descriptive_text():
    requirements = extract_requirements(
        uuid4(), "rules.txt",
        "Upload a photo ID. Upload a photo ID. We review applications weekly.",
    )
    assert len(requirements) == 1
    assert requirements[0].description == "Upload a photo ID."


def test_instruction_provenance_identifies_source_without_claiming_compliance():
    source = uuid4()
    evidence = instruction_provenance(source, "rules.txt", "Provide a photo ID.")
    assert evidence.source_document_id == source
    assert evidence.source_label == "rules.txt"
    assert evidence.excerpt == "Provide a photo ID."


def test_explicit_waivers_are_not_reported_as_required_actions():
    requirements = extract_requirements(
        uuid4(), "waivers.txt",
        "You do not need to upload a passport. "
        "It is not required to provide bank statements. "
        "There is no need to submit an extra photo. "
        "You must provide a signed consent form.",
    )
    assert len(requirements) == 1
    assert requirements[0].description == "You must provide a signed consent form."
    assert requirements[0].status.value == "pending"


def test_ambiguous_negation_is_not_silently_dropped():
    requirements = extract_requirements(
        uuid4(), "conditions.txt",
        "You must not upload confidential customer records.",
    )
    assert len(requirements) == 1
    assert requirements[0].description == "You must not upload confidential customer records."


def test_contrasting_waiver_does_not_hide_mandatory_obligation():
    requirements = extract_requirements(
        uuid4(), "mixed.txt",
        "You do not need to upload a passport, but you must provide proof of income. "
        "No need to submit a photo; however, you must not share confidential data.",
    )
    assert len(requirements) == 2
    assert requirements[0].description == "you must provide proof of income."
    assert requirements[1].description == "you must not share confidential data."
    assert all(requirement.status.value == "pending" for requirement in requirements)
    assert all(not requirement.evidence for requirement in requirements)


def test_optional_document_statements_are_not_misclassified_as_obligations():
    requirements = extract_requirements(
        uuid4(),
        "optional.txt",
        "A passport is not required. "
        "A cover letter is not necessary. "
        "A signed consent form is required. "
        "You must not share confidential records.",
    )
    assert [requirement.description for requirement in requirements] == [
        "A signed consent form is required.",
        "You must not share confidential records.",
    ]
    assert all(not requirement.evidence for requirement in requirements)


def test_contracted_waivers_do_not_create_false_requirements():
    requirements = extract_requirements(
        uuid4(),
        "contractions.txt",
        "You don't need to upload a passport. "
        "An applicant doesn’t need to submit a second photo. "
        "You must provide proof of income. "
        "You must not upload confidential records.",
    )
    assert [item.description for item in requirements] == [
        "You must provide proof of income.",
        "You must not upload confidential records.",
    ]
    assert all(not item.evidence for item in requirements)
