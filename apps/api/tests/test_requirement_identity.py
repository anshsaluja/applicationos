from uuid import uuid4

from app.extraction import extract_requirements


def test_requirement_ids_stable_across_repeated_extraction():
    document_id = uuid4()
    text = "You must provide proof of address. Submit a valid ID."
    first = extract_requirements(document_id, "instructions.txt", text)
    second = extract_requirements(document_id, "instructions.txt", text)
    assert len(first) == 2
    assert [item.id for item in first] == [item.id for item in second]
    assert len({item.id for item in first}) == 2


def test_requirement_ids_scoped_to_source_document():
    text = "You must provide proof of address."
    left = extract_requirements(uuid4(), "a.txt", text)
    right = extract_requirements(uuid4(), "b.txt", text)
    assert left[0].id != right[0].id


def test_duplicate_instructions_do_not_create_extra_candidates():
    document_id = uuid4()
    items = extract_requirements(document_id, "a.txt", "Submit a valid ID. Submit a valid ID.")
    assert len(items) == 1
