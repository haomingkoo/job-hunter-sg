import json
from pathlib import Path


def test_current_corpus_scope_receipt_retains_each_singapore_location_family():
    receipt = json.loads(
        (Path(__file__).resolve().parents[1] / "evals/work-location-scope-v1.coverage.json").read_text()
    )

    assert receipt["classifier_version"] == "work-location-scope-v1"
    sources = receipt["sources"]
    assert set(sources) == {"MyCareersFuture"}
    source = sources["MyCareersFuture"]
    assert source["provenance"] == "legacy_mcf_source_provisional_v1"
    assert set(source["location_families"]) == {
        "building_or_address_label",
        "canonical_region",
    }
    for counts in source["location_families"].values():
        assert counts["singapore"] > counts["overseas"]
        assert counts["unknown"] == 0

    totals = {
        scope: sum(family[scope] for family in source["location_families"].values())
        for scope in ("singapore", "overseas", "unknown")
    }
    assert totals == source["totals"]
    assert sum(totals.values()) == receipt["corpus"]["visible_job_count"]
