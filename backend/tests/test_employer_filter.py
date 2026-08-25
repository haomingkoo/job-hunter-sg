from sqlalchemy import Column, MetaData, String, Table, create_engine, select

from employer_filter import (
    EMPLOYER_RELATIONSHIP_DIRECT,
    EMPLOYER_RELATIONSHIP_INTERMEDIARY,
    EMPLOYER_RELATIONSHIP_UNKNOWN,
    classify_employer_relationship,
    company_name_matches,
    direct_employer_condition,
    employer_relationship_eligibility_condition,
    employer_relationship_valid_condition,
    is_direct_employer,
    is_recruitment_employer,
)


def test_relationship_classifier_never_upgrades_absence_of_agency_evidence_to_direct():
    unknown = classify_employer_relationship(
        source="MyCareersFuture",
        company="Micron Semiconductor",
        ssic_code="26112",
        ssic_source="mcf_posted_company",
        description="Lead quality systems.",
    )
    intermediary = classify_employer_relationship(
        source="MyCareersFuture",
        company="Acme Talent Solutions Pte Ltd",
        ssic_code="78104",
        ssic_source="mcf_posted_company",
        description="Client opportunities.",
    )
    direct = classify_employer_relationship(
        source="Careers@Gov",
        company="Singapore Public Service",
        agency="Ministry of Trade and Industry",
        description="Join the ministry.",
    )

    assert (unknown.relationship, unknown.evidence) == (
        EMPLOYER_RELATIONSHIP_UNKNOWN,
        "mcf_no_relationship_signal",
    )
    assert (intermediary.relationship, intermediary.evidence) == (
        EMPLOYER_RELATIONSHIP_INTERMEDIARY,
        "mcf_posted_company_ssic_78",
    )
    assert (direct.relationship, direct.evidence) == (
        EMPLOYER_RELATIONSHIP_DIRECT,
        "careers_gov_official",
    )


def test_mcf_non_recruitment_code_does_not_claim_ssic_78_provenance():
    assessment = classify_employer_relationship(
        source="MyCareersFuture",
        company="Example Services",
        ssic_code="26112",
        ssic_description="Recruitment support activities",
        ssic_source="mcf_posted_company",
        description="Support hiring operations.",
    )

    assert assessment.relationship == EMPLOYER_RELATIONSHIP_INTERMEDIARY
    assert assessment.evidence == "mcf_posted_company_ssic_description"


def test_relationship_sql_policy_includes_unknown_but_requires_valid_evidence():
    metadata = MetaData()
    employers = Table(
        "relationship_employers",
        metadata,
        Column("company", String),
        Column("relationship", String),
        Column("evidence", String),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    rows = [
        {"company": "Gov", "relationship": "direct", "evidence": "careers_gov_official"},
        {"company": "Micron", "relationship": "unknown", "evidence": "mcf_no_relationship_signal"},
        {"company": "Recruiter", "relationship": "intermediary", "evidence": "description_ea_licence"},
        {"company": "False Claim", "relationship": "direct", "evidence": "mcf_no_relationship_signal"},
    ]
    with engine.begin() as connection:
        connection.execute(employers.insert(), rows)
        eligible = (
            connection.execute(
                select(employers.c.company).where(
                    employer_relationship_eligibility_condition(
                        employers.c.relationship,
                        employers.c.evidence,
                        employers.c.company,
                    )
                )
            )
            .scalars()
            .all()
        )
        valid = (
            connection.execute(
                select(employers.c.company).where(
                    employer_relationship_valid_condition(
                        employers.c.relationship,
                        employers.c.evidence,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert eligible == ["Gov", "Micron"]
    assert valid == ["Gov", "Micron", "Recruiter"]


def test_company_name_matching_uses_normalized_whole_words():
    assert company_name_matches("MICRON SEMICONDUCTOR ASIA OPERATIONS PTE. LTD.", "Micron")
    assert company_name_matches("ST Engineering Electronics", "ST Engineering")
    assert not company_name_matches("ECOMICRON SYSTEMS", "Micron")
    assert not company_name_matches("Micron", "")


def test_verified_agencies_and_ea_licence_markers_are_recruiters():
    for company in (
        "Allied Search Pte. Ltd.",
        "Sinweb Manpower Consultant",
        "Search Avenue Pte Ltd",
        "Oaktree Consulting",
        "Direct Search Asia Pte. Ltd.",
        "Asia Search Pte. Ltd.",
        "Asia-Search Pte. Ltd.",
        "Kerry Consulting Pte. Ltd.",
        "AISEARCH PTE. LTD.",
        "Starsearch",
        "Placement Professionals",
        "BGC Group Pte. Ltd.",
        "Ethos Search Associates Pte. Ltd.",
        "SKILMATCH RECRUIMENT",
        "Talent Spot Group Private Ltd.",
        "J&L Apex Advisory Pte. Ltd.",
        "ADABA Pte. Ltd.",
        "APBA TG Human Resource Pte. Ltd.",
        "First Konnection Pte. Ltd.",
        "SearchAsia Consulting Pte. Ltd.",
        "One Search Consulting Pte. Ltd.",
        "GMP-TECHNOLOGIES (S) PTE LTD",
        "Raffles Employment Pte. Ltd.",
        "LH Manpower Service Pte. Ltd.",
    ):
        assert is_recruitment_employer(company)

    assert is_recruitment_employer(
        "Example Services Pte Ltd",
        description="EA Licence No: 12C3456",
    )
    assert is_recruitment_employer(
        "Example Services Pte Ltd",
        description="Employment Agency License No. 12C3456",
    )
    assert is_recruitment_employer(
        "Example Services Pte Ltd",
        description="EA/ Licence No: 12C3456",
    )
    assert is_recruitment_employer(
        "Opaque Advisory Pte Ltd",
        description="EA No. 26S3529 | EA Personnel No. R1329267",
    )
    assert is_recruitment_employer(
        "MTC Consulting Pte. Ltd.",
        description="Consultant registration R24124448, agency licence 15C7752.",
    )
    assert is_recruitment_employer(
        "Example Solutions Pte. Ltd.",
        description=(
            "An established semiconductor component distributor is looking for "
            "a Sales Manager to lead its regional team."
        ),
    )
    assert is_recruitment_employer(
        "Example Advisory Pte. Ltd.",
        description="Our client is a global manufacturer seeking a Quality Manager.",
    )


def test_alias_and_description_checks_avoid_nearby_false_positives():
    assert not is_recruitment_employer("AI Search Technologies")
    assert not is_recruitment_employer("Starsearching Labs")
    assert not is_recruitment_employer(
        "Example Software Pte Ltd",
        description="Manage software licence renewals for the EA platform.",
    )
    assert not is_direct_employer("")
    assert not is_recruitment_employer(
        "Example Shipping Pte Ltd",
        description="A valid sea licence is required.",
    )
    assert not is_recruitment_employer(
        "Example Marine Pte Ltd",
        description="SEA personnel coordinate vessel operations.",
    )
    assert not is_recruitment_employer(
        "Established Components Pte Ltd",
        description="We are an established manufacturer looking for a Quality Manager.",
    )
    assert not is_recruitment_employer(
        "Example Electronics Pte Ltd",
        description="Build durable relationships because our clients require quality.",
    )


def test_sql_condition_matches_python_classification():
    metadata = MetaData()
    employers = Table(
        "employers",
        metadata,
        Column("company", String),
        Column("ssic", String),
        Column("description", String),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    rows = [
        {
            "company": "Direct Search Asia Pte. Ltd.",
            "ssic": "",
            "description": "Technology role.",
        },
        {
            "company": "Asia Search Pte. Ltd.",
            "ssic": "",
            "description": "Semiconductor role.",
        },
        {
            "company": "Asia-Search Pte. Ltd.",
            "ssic": "",
            "description": "Semiconductor role.",
        },
        {
            "company": "Kerry Consulting Pte. Ltd.",
            "ssic": "",
            "description": "Production role.",
        },
        {
            "company": "J&L Apex Advisory Pte. Ltd.",
            "ssic": "",
            "description": "EA No. 26S3529 | EA Personnel No. R1329267",
        },
        {
            "company": "SKILMATCH RECRUIMENT",
            "ssic": "",
            "description": "Sales role.",
        },
        {
            "company": "APBA TG Human Resource Pte. Ltd.",
            "ssic": "",
            "description": "Recruitment consultant role.",
        },
        {
            "company": "Example Services Pte Ltd",
            "ssic": "",
            "description": "EA/ License No: 12C3456",
        },
        {
            "company": "Example Search Pte Ltd",
            "ssic": "",
            "description": "Consultant: (EA License No: 12C3456)",
        },
        {
            "company": "MTC Consulting Pte. Ltd.",
            "ssic": "",
            "description": "Consultant registration R24124448, agency licence 15C7752.",
        },
        {
            "company": "Axiom Services Pte Ltd",
            "ssic": "",
            "description": "Registered employment agency (license #12S5884).",
        },
        {
            "company": "Example Solutions Pte Ltd",
            "ssic": "",
            "description": "An established semiconductor distributor is looking for a Sales Manager.",
        },
        {
            "company": "Example Advisory Pte Ltd",
            "ssic": "",
            "description": "Our client is a global manufacturer seeking a Quality Manager.",
        },
        {
            "company": "Example Software Pte Ltd",
            "ssic": "Software publishing",
            "description": "Manage software licence renewals for the EA platform.",
        },
        {
            "company": "Starsearching Labs",
            "ssic": "Research and development",
            "description": "Astronomy software role.",
        },
        {
            "company": "Example Shipping Pte Ltd",
            "ssic": "Shipping",
            "description": "A valid sea licence is required.",
        },
        {
            "company": "Direct Employer Pte Ltd",
            "ssic": None,
            "description": None,
        },
        {
            "company": "Established Components Pte Ltd",
            "ssic": "Manufacturing",
            "description": "We are an established manufacturer looking for a Quality Manager.",
        },
        {
            "company": "GMP-TECHNOLOGIES (S) PTE LTD",
            "ssic": "",
            "description": "Quality role.",
        },
        {
            "company": None,
            "ssic": "",
            "description": "Unknown employer role.",
        },
    ]
    with engine.begin() as connection:
        connection.execute(employers.insert(), rows)
        direct_companies = set(
            connection.execute(
                select(employers.c.company).where(
                    direct_employer_condition(
                        employers.c.company,
                        employers.c.ssic,
                        employers.c.description,
                    )
                )
            ).scalars()
        )

    expected_direct = {
        row["company"]
        for row in rows
        if is_direct_employer(
            row["company"],
            row["ssic"],
            row["description"],
        )
    }
    assert direct_companies == expected_direct
