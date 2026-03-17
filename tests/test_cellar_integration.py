import os

import pytest

from cellar_extractor import cellar
from cellar_extractor.cellar_queries import get_all_eclis, get_raw_cellar_metadata


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CELLAR_INTEGRATION") != "1",
    reason="Set RUN_CELLAR_INTEGRATION=1 to run live CELLAR metadata integration tests.",
)

START_DATE = "2025-01-01"
END_DATE = "2025-01-31"


def _sample_eclis(limit=3):
    eclis = get_all_eclis(starting_date=START_DATE, ending_date=END_DATE, limit=10)
    eu_eclis = [ecli for ecli in eclis if ecli.startswith("ECLI:EU:")]
    assert len(eu_eclis) >= limit
    return eu_eclis[:limit]


def _normalize_csv_celexes(value):
    return {part.strip() for part in str(value).split(";") if part.strip()}


def test_get_all_eclis_live_limit_is_respected_and_sorted():
    eclis = get_all_eclis(starting_date=START_DATE, ending_date=END_DATE, limit=5)

    assert len(eclis) == 5
    assert eclis == sorted(eclis)
    assert all(ecli.startswith("ECLI:") for ecli in eclis)


def test_get_all_eclis_live_large_limit_matches_small_limit_prefix():
    small = get_all_eclis(starting_date=START_DATE, ending_date=END_DATE, limit=5)
    large = get_all_eclis(starting_date=START_DATE, ending_date=END_DATE, limit=10_000_000)

    assert len(large) >= len(small)
    assert large[: len(small)] == small


def test_get_raw_cellar_metadata_live_returns_requested_documents_with_core_fields():
    eclis = _sample_eclis(limit=3)

    metadata = get_raw_cellar_metadata(eclis)

    assert set(metadata) == set(eclis)
    for ecli in eclis:
        row = metadata[ecli]
        assert row["ECLI"] == [ecli]
        assert row["Celex identifier"][0].strip() != ""
        assert row["Date of document"][0].strip() != ""
        assert row["Sector identifier"][0].strip() != ""


def test_get_cellar_live_csv_preserves_requested_count_and_core_columns():
    expected_eclis = _sample_eclis(limit=3)
    payload = get_raw_cellar_metadata(expected_eclis)
    expected_celexes = {payload[ecli]["Celex identifier"][0].strip() for ecli in expected_eclis}

    df = cellar.get_cellar(
        ed=END_DATE,
        save=False,
        max_ecli=4,
        sd=START_DATE,
        file_format="csv",
    )

    matched_rows = df[
        df["CELEX IDENTIFIER"]
        .fillna("")
        .astype(str)
        .map(lambda value: bool(_normalize_csv_celexes(value) & expected_celexes))
    ]
    matched_celexes = set()
    for value in matched_rows["CELEX IDENTIFIER"].fillna("").astype(str):
        matched_celexes.update(_normalize_csv_celexes(value) & expected_celexes)

    assert matched_celexes == expected_celexes
    for column in ["CELEX IDENTIFIER", "DATE OF DOCUMENT", "SECTOR IDENTIFIER"]:
        values = matched_rows[column].fillna("").astype(str).str.strip()
        assert values.ne("").all()
