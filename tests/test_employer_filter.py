import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from employer_filter import is_recruitment_employer


def test_recruitment_employers_are_detected():
    assert is_recruitment_employer("RECRUIT EXPRESS PTE LTD")
    assert is_recruitment_employer("THE SUPREME HR ADVISORY PTE. LTD.")
    assert is_recruitment_employer("PERSOL SINGAPORE PTE. LTD.")
    assert is_recruitment_employer("MANPOWER STAFFING SERVICES (SINGAPORE) PTE LTD")


def test_direct_employers_are_kept():
    assert not is_recruitment_employer("NATIONAL UNIVERSITY OF SINGAPORE")
    assert not is_recruitment_employer("A*STAR RESEARCH ENTITIES")
    assert not is_recruitment_employer("DBS BANK LTD")
    assert not is_recruitment_employer("STMICROELECTRONICS PTE LTD")


def test_official_ssic_description_can_identify_employment_agencies():
    assert is_recruitment_employer(
        "GENERIC HOLDINGS PTE LTD",
        "Employment agencies and executive search services",
    )
