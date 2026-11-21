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


def test_semicolon_waiver_cannot_hide_independent_mandatory_requirement():
    source = uuid4()
    requirements = extract_requirements(
        source,
        "mixed-clauses.txt",
        "You do not need to upload a passport; you must provide proof of income. "
        "Submit a signed consent form; no need to submit a second photograph.",
    )
    assert [item.description for item in requirements] == [
        "you must provide proof of income.",
        "Submit a signed consent form",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)
    assert all(item.id.version == 5 for item in requirements)


def test_semicolon_clauses_deduplicate_and_keep_stable_ids():
    source = uuid4()
    text = "Upload a photo ID; Upload a photo ID; You do not need to upload a passport."
    first = extract_requirements(source, "one.txt", text)
    second = extract_requirements(source, "renamed.txt", text)
    assert len(first) == 1
    assert first[0].description == "Upload a photo ID"
    assert first[0].id == second[0].id


def test_conjunction_waiver_cannot_hide_independent_obligation():
    requirements = extract_requirements(
        uuid4(),
        "conjoined.txt",
        "You do not need to upload a passport and you must provide proof of income. "
        "A photograph is not required and applicants shall submit a signed consent form.",
    )
    assert [item.description for item in requirements] == [
        "you must provide proof of income.",
        "applicants shall submit a signed consent form.",
    ]
    assert all(item.evidence == [] for item in requirements)


def test_conjunction_inside_document_list_remains_single_requirement():
    requirements = extract_requirements(
        uuid4(), "list.txt", "You must upload a passport and a photograph."
    )
    assert [item.description for item in requirements] == [
        "You must upload a passport and a photograph."
    ]


def test_subject_elided_mandatory_clause_survives_waiver():
    requirements = extract_requirements(
        uuid4(),
        "short-conjunction.txt",
        "You do not need to upload a passport and must provide proof of income. "
        "Applicants need not submit a photo and shall include a signed declaration.",
    )
    assert [item.description for item in requirements] == [
        "must provide proof of income.",
        "shall include a signed declaration.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_coordinated_document_objects_do_not_split():
    requirements = extract_requirements(
        uuid4(),
        "objects.txt",
        "You must provide a passport and a photograph.",
    )
    assert [item.description for item in requirements] == [
        "You must provide a passport and a photograph."
    ]


def test_descriptive_action_verbs_are_not_misread_as_requirements():
    requirements = extract_requirements(
        uuid4(),
        "overview.txt",
        "We provide support during business hours. "
        "You may upload a photograph for your profile. "
        "The portal includes an optional checklist. "
        "Please submit a signed consent form. "
        "You must provide proof of address.",
    )
    assert [item.description for item in requirements] == [
        "Please submit a signed consent form.",
        "You must provide proof of address.",
    ]
    assert all(item.evidence == [] for item in requirements)


def test_imperative_action_verbs_remain_supported():
    requirements = extract_requirements(
        uuid4(), "instructions.txt",
        "Provide an ID. Submit a form. Upload proof of address. Include a signature.",
    )
    assert len(requirements) == 4
    assert all(item.status.value == "pending" for item in requirements)


def test_decimal_quantities_are_preserved_in_requirement_provenance():
    requirements = extract_requirements(
        uuid4(),
        "service-levels.txt",
        "The service must maintain 99.9% availability. "
        "The system shall respond within 0.5 seconds. "
        "This is descriptive context.",
    )
    assert [item.description for item in requirements] == [
        "The service must maintain 99.9% availability.",
        "The system shall respond within 0.5 seconds.",
    ]
    assert all(item.evidence == [] for item in requirements)


def test_yet_and_nevertheless_waivers_do_not_hide_obligations():
    requirements = extract_requirements(
        uuid4(),
        "contrasts.txt",
        "You do not need to submit a passport, yet you must provide proof of address. "
        "A photograph is not required; nevertheless applicants shall include a signature. "
        "The cover letter is optional.",
    )
    assert [item.description for item in requirements] == [
        "you must provide proof of address.",
        "applicants shall include a signature.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_contracted_must_not_prohibitions_remain_pending_requirements():
    requirements = extract_requirements(
        uuid4(),
        "prohibitions.txt",
        "You mustn't disclose customer credentials. "
        "Applicants mustn’t upload private keys. "
        "A cover letter is not required.",
    )
    assert [item.description for item in requirements] == [
        "You mustn't disclose customer credentials.",
        "Applicants mustn’t upload private keys.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_mandatory_and_compulsory_obligations_and_waivers():
    requirements = extract_requirements(
        uuid4(),
        "policy.txt",
        "A signed disclosure is mandatory. "
        "An identity check is compulsory. "
        "A cover letter is not mandatory. "
        "An extra photograph is not compulsory.",
    )
    assert [item.description for item in requirements] == [
        "A signed disclosure is mandatory.",
        "An identity check is compulsory.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_contracted_policy_waivers_do_not_create_false_requirements():
    requirements = extract_requirements(
        uuid4(),
        "contracted-waivers.txt",
        "A cover letter isn't required. "
        "Additional photographs aren't mandatory. "
        "A second interview wasn't compulsory. "
        "Previous references weren't necessary. "
        "A signed consent form is mandatory. "
        "A passport isn't required, but proof of address must be supplied.",
    )
    assert [item.description for item in requirements] == [
        "A signed consent form is mandatory.",
        "proof of address must be supplied.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_whereas_and_although_waivers_preserve_separate_obligations():
    requirements = extract_requirements(
        uuid4(),
        "contrasting-policies.txt",
        "A cover letter is not required, whereas a signed declaration is mandatory. "
        "A photograph is not compulsory, although applicants must provide proof of address.",
    )
    assert [item.description for item in requirements] == [
        "a signed declaration is mandatory.",
        "applicants must provide proof of address.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_explicit_prohibitions_are_pending_without_fabricated_evidence():
    requirements = extract_requirements(
        uuid4(),
        "security-policy.txt",
        "Sharing customer credentials is prohibited. "
        "Uploading private keys is forbidden. "
        "Publishing a public URL is not prohibited. "
        "Sharing a test fixture isn’t forbidden.",
    )
    assert [item.description for item in requirements] == [
        "Sharing customer credentials is prohibited.",
        "Uploading private keys is forbidden.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_bulleted_imperatives_are_pending_and_retain_exact_source_excerpt():
    requirements = extract_requirements(
        uuid4(),
        "checklist.txt",
        "- Upload a photo ID.\n"
        "* Submit a signed form.\n"
        "• Please provide proof of address.\n"
        "- You may upload an optional portrait.\n"
        "This is informational context.",
    )
    assert [item.description for item in requirements] == [
        "- Upload a photo ID.",
        "* Submit a signed form.",
        "• Please provide proof of address.",
    ]
    assert all(item.status.value == "pending" for item in requirements)
    assert all(item.evidence == [] for item in requirements)


def test_numbered_checklist_imperatives_preserve_provenance_and_ignore_optional_items():
    source = uuid4()
    text = (
        "1. Upload a photo ID.\n"
        "2) Please submit a signed consent form.\n"
        "3. You may provide an optional portrait.\n"
        "4) Include proof of address."
    )
    first = extract_requirements(source, "numbered.txt", text)
    second = extract_requirements(source, "renamed.txt", text)
    assert [item.description for item in first] == [
        "1. Upload a photo ID.",
        "2) Please submit a signed consent form.",
        "4) Include proof of address.",
    ]
    assert [item.id for item in first] == [item.id for item in second]
    assert all(item.status.value == "pending" and not item.evidence for item in first)


def test_have_to_obligations_and_contracted_waivers_remain_distinct():
    source = uuid4()
    text = (
        "Applicants have to provide proof of address. "
        "The reviewer has to verify the signed consent form. "
        "You don't have to upload a passport, but you must provide a photo ID. "
        "A guest does not have to submit a second reference. "
        "You do not have to include an optional biography."
    )
    first = extract_requirements(source, "obligations.txt", text)
    second = extract_requirements(source, "renamed.txt", text)
    assert [item.description for item in first] == [
        "Applicants have to provide proof of address.",
        "The reviewer has to verify the signed consent form.",
        "you must provide a photo ID.",
    ]
    assert [item.id for item in first] == [item.id for item in second]
    assert all(item.status.value == "pending" and item.evidence == [] for item in first)


def test_have_to_waiver_does_not_hide_conjoined_obligation():
    requirements = extract_requirements(
        uuid4(), "conjunction.txt",
        "You do not have to upload a passport and must provide proof of address.",
    )
    assert [item.description for item in requirements] == [
        "must provide proof of address."
    ]



def test_coordinated_reviewer_obligations_are_independent_and_auditable():
    source = uuid4()
    text = (
        "Applicants must upload proof of address and the reviewer must verify the signature. "
        "You do not need to provide a passport and reviewers shall record the decision. "
        "You must upload a passport and a photograph."
    )
    first = extract_requirements(source, "policy.txt", text)
    second = extract_requirements(source, "renamed.txt", text)
    assert [item.description for item in first] == [
        "Applicants must upload proof of address",
        "the reviewer must verify the signature.",
        "reviewers shall record the decision.",
        "You must upload a passport and a photograph.",
    ]
    assert [item.id for item in first] == [item.id for item in second]
    assert all(item.status.value == "pending" and item.evidence == [] for item in first)
