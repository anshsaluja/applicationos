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
