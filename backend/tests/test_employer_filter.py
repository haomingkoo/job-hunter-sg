from sqlalchemy import Column, MetaData, String, Table, create_engine, select

from employer_filter import direct_employer_condition, is_recruitment_employer


def test_verified_agencies_and_ea_licence_markers_are_recruiters():
    for company in (
        "Allied Search Pte. Ltd.",
        "Sinweb Manpower Consultant",
        "Search Avenue Pte Ltd",
        "Oaktree Consulting",
        "Direct Search Asia Pte. Ltd.",
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


def test_alias_and_description_checks_avoid_nearby_false_positives():
    assert not is_recruitment_employer("AI Search Technologies")
    assert not is_recruitment_employer("Starsearching Labs")
    assert not is_recruitment_employer(
        "Example Software Pte Ltd",
        description="Manage software licence renewals for the EA platform.",
    )
    assert not is_recruitment_employer(
        "Example Shipping Pte Ltd",
        description="A valid sea licence is required.",
    )
    assert not is_recruitment_employer(
        "Example Marine Pte Ltd",
        description="SEA personnel coordinate vessel operations.",
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
        if not is_recruitment_employer(
            row["company"],
            row["ssic"],
            row["description"],
        )
    }
    assert direct_companies == expected_direct
