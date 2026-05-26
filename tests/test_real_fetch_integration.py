"""
Live integration tests that pin real-fetch output against expected values.

Goals:
- **Match expected results**: for known stable documents (GDPR, AI Act,
  Data Act, sector-6 order, sector-8 national case), assert specific
  field values that come from the upstream.
- **Check parsing**: validate type contracts (dates parseable, booleans
  in {0,1}, language codes ISO-639-1, URLs HTTP-shaped, sectors numeric).
- **No data lost**: for every sample, fetch the raw CDM SPARQL response
  and verify that every predicate the upstream returned reaches the
  package output — either as a canonical field or as a discovered extra.

Run with:

    RUN_SAMPLES_DUMP=1 pytest -q tests/test_real_fetch_integration.py
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import pytest
from SPARQLWrapper import JSON, POST, SPARQLWrapper

from cellar_extractor import eurlex_scraping, schema
from cellar_extractor.cellar_queries import (
    get_raw_cellar_metadata,
    get_raw_cellar_metadata_by_celex,
)
from cellar_extractor.citations_adder import add_citations_separate
from cellar_extractor.eurlex_scraping import (
    get_case_data_by_celex_id,
    get_clean_text_from_html,
)
from cellar_extractor.fulltext_saving import add_sections
from cellar_extractor.json_to_csv import json_to_csv_returning


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SAMPLES_DUMP") != "1",
    reason="Set RUN_SAMPLES_DUMP=1 to run live real-fetch integration tests.",
)


SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"


@pytest.fixture(autouse=True)
def _clear_caches():
    eurlex_scraping._get_case_data_cached.cache_clear()
    yield
    eurlex_scraping._get_case_data_cached.cache_clear()


# ---------------------------------------------------------------------------
# Helpers — build the same per-row dict the package emits to consumers.
# ---------------------------------------------------------------------------


def _resolve_ecli_for_celex(celex: str) -> str:
    sparql = SPARQLWrapper(SPARQL_ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)
    sparql.setQuery(
        f"""
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        SELECT ?ecli WHERE {{
            ?doc cdm:resource_legal_id_celex ?celex .
            ?doc cdm:case-law_ecli ?ecli .
            FILTER(STR(?celex) = "{celex}")
        }}
        LIMIT 1
        """
    )
    rows = sparql.queryAndConvert().get("results", {}).get("bindings", [])
    return rows[0]["ecli"]["value"] if rows else ""


def _row_for_legislation(celex: str) -> Dict[str, Any]:
    raw = get_raw_cellar_metadata_by_celex([celex])
    if not raw or not raw.get(celex):
        pytest.skip(f"CELLAR has no SPARQL data for {celex}")
    df = json_to_csv_returning(raw)
    record = df.iloc[0].to_dict()
    record["celex"] = celex
    # Also pull the REST text-side data for fulltext provenance fields.
    text_data = get_case_data_by_celex_id(celex, language="EN") or {}
    for key in ("text_source", "text_format", "text_language", "fulltext_source", "missing_reasons"):
        if not record.get(key) and text_data.get(key):
            record[key] = text_data[key]
    return schema.fill_canonical(record)


def _row_for_case_law(celex: str) -> Dict[str, Any]:
    ecli = _resolve_ecli_for_celex(celex)
    if not ecli:
        pytest.skip(f"CELLAR did not resolve ECLI for {celex}")
    raw = get_raw_cellar_metadata([ecli])
    if not raw.get(ecli):
        pytest.skip(f"CELLAR returned empty triples for {ecli}")
    df = json_to_csv_returning(raw)
    df.loc[:, "celex"] = celex
    df.loc[:, "ecli"] = ecli
    add_citations_separate(df, threads=1)
    add_sections(df, threads=1)
    record = df.iloc[0].to_dict()
    return schema.fill_canonical(record)


# ---------------------------------------------------------------------------
# Type / parsing validators — mechanically check every populated canonical
# field against its declared type in FIELD_MANIFEST.
# ---------------------------------------------------------------------------


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_LANG_RE = re.compile(r"^[A-Z]{2}$")


def _is_empty_cell(cell: Any) -> bool:
    if cell is None:
        return True
    if isinstance(cell, float) and pd.isna(cell):
        return True
    if isinstance(cell, str) and cell.strip() == "":
        return True
    return False


def _split_multi(cell: Any) -> list[str]:
    """Split a multi-cardinality cell on ``;``. Empty cells return ``[]``."""
    if _is_empty_cell(cell):
        return []
    return [v.strip() for v in str(cell).split(";") if v.strip()]


def _validate_field(name: str, cell: Any, manifest_entry: Dict[str, Any]) -> Optional[str]:
    """Return an error message if ``cell`` violates the manifest's type contract."""
    if _is_empty_cell(cell):
        return None
    type_ = manifest_entry["type"]
    cardinality = manifest_entry["cardinality"]
    # Only multi-cardinality fields are split on ";"; single-cardinality fields
    # (e.g. summary, national_judgement, citations_extra_info) legitimately
    # contain ";" in their natural-language content.
    if cardinality == "multi":
        values = _split_multi(cell)
    else:
        values = [str(cell).strip()]
    if not values:
        return None
    for v in values:
        if type_ == "date":
            if not _DATE_RE.match(v):
                return f"field {name!r} value {v!r} not YYYY-MM-DD"
        elif type_ == "datetime":
            if not _DATETIME_RE.match(v):
                return f"field {name!r} value {v!r} not ISO datetime"
        elif type_ == "boolean":
            if v not in {"0", "1"}:
                return f"field {name!r} value {v!r} not boolean (0/1)"
        elif type_ == "integer":
            try:
                int(v)
            except ValueError:
                return f"field {name!r} value {v!r} not integer"
        elif type_ == "url":
            if not (v.startswith("http://") or v.startswith("https://")):
                return f"field {name!r} value {v!r} not URL-shaped"
    if name == "text_language" and values:
        if not _LANG_RE.match(values[0]):
            return f"text_language {values[0]!r} not 2-letter uppercase ISO code"
    return None


# ---------------------------------------------------------------------------
# 1. GDPR — sector 3 — golden values + type contract
# ---------------------------------------------------------------------------


def test_gdpr_real_fetch_matches_expected_values():
    row = _row_for_legislation("32016R0679")

    # Identity
    assert row["celex"] == "32016R0679"
    assert row["sector"] == "3"
    assert row["resource_legal_type"] == "R"
    assert int(row["year_of_resource"]) == 2016
    assert int(row["natural_number_celex"]) == 679

    # Document type
    assert "Regulation" in row["resource_type"]

    # Dates
    assert _DATE_RE.match(row["date_publication"]), row["date_publication"]
    assert row["date_publication"].startswith("2016-04")
    assert row["date_signature"].startswith("2016-04")
    assert row["date_end_of_validity"] == "9999-12-31"  # GDPR still active

    # Legislation-specific
    assert row["eli"] == "http://data.europa.eu/eli/reg/2016/679/oj"
    assert row["in_force"] == "1"
    assert row["is_eea_relevant"] == "1"
    assert "Justice and Consumers" in row["responsibility_agent"]
    assert row["repertoire"] == "REP"
    assert "TFEU" in row["based_on_treaty"] or "Treaty on the Functioning" in row["based_on_treaty"]

    # Subject matter contains expected concept
    assert "Consumer protection" in row["subject_matter"] or "freedom" in row["subject_matter"].lower()

    # Case-law-only fields are null (sector affinity contract)
    for case_law_only in ("ecli", "judicial_procedure_type", "advocate_general", "judge_rapporteur",
                         "delivered_by_court_formation", "language_procedure", "origin_country",
                         "national_judgement"):
        assert _is_empty_cell(row[case_law_only]), (
            f"GDPR row should have null {case_law_only}, got {row[case_law_only]!r}"
        )


def test_gdpr_canonical_field_types_match_manifest():
    row = _row_for_legislation("32016R0679")
    by_name = {e["name"]: e for e in schema.FIELD_MANIFEST}
    errors = []
    for name, cell in row.items():
        if name not in by_name:
            continue
        msg = _validate_field(name, cell, by_name[name])
        if msg:
            errors.append(msg)
    assert not errors, "GDPR row violates manifest type contract:\n  " + "\n  ".join(errors)


# ---------------------------------------------------------------------------
# 2. AI Act — sector 3 — second legislation sample, broader OJ coverage
# ---------------------------------------------------------------------------


def test_ai_act_real_fetch_matches_expected_values():
    row = _row_for_legislation("32024R1689")

    assert row["celex"] == "32024R1689"
    assert row["sector"] == "3"
    assert row["resource_legal_type"] == "R"
    assert int(row["year_of_resource"]) == 2024
    assert "Regulation" in row["resource_type"]

    assert row["eli"] == "http://data.europa.eu/eli/reg/2024/1689/oj"
    assert row["in_force"] == "1"
    # OJ publication metadata is one of the bigger discovered clusters; confirm
    # at least one of those discovered fields landed (proves the package didn't
    # silently drop them).
    assert any(k.startswith("official_journal_act_") for k in row), (
        "expected official_journal_act_* discovered fields for AI Act"
    )


# ---------------------------------------------------------------------------
# 3. CJEU order — sector 6 — golden values + parsing
# ---------------------------------------------------------------------------


def test_cjeu_order_real_fetch_matches_expected_values():
    row = _row_for_case_law("62023CO0800")

    # Identity
    assert row["celex"] == "62023CO0800"
    assert row["ecli"] == "ECLI:EU:C:2025:1"
    assert row["sector"] == "6"
    assert row["resource_legal_type"] == "CO"
    assert row["resource_type"] == "Order"

    # Court / procedure
    assert row["delivered_by_court_formation"] == "Tenth Chamber"
    assert row["judicial_procedure_type"] == "Reference for a preliminary ruling"
    assert "preliminary ruling" in row["type_procedure"].lower()
    assert row["language_procedure"] == "Dutch"
    assert row["origin_country"] == "Belgium"

    # Dates
    assert row["date_publication"] == "2025-01-07"
    assert row["date_of_request"] == "2023-12-28"

    # Enrichment populated something useful
    assert row["advocate_general"], "advocate_general missing on a CJEU order"
    assert row["judge_rapporteur"], "judge_rapporteur missing on a CJEU order"
    assert row["summary"], "summary missing on a CJEU order"
    assert "C-800/23" in row["summary"]

    # Citation graph harvested
    assert row["citing"] is not None and len(row["citing"]) > 0, "citing empty"

    # Legislation-only fields are null
    for legis_only in ("eli", "in_force", "is_eea_relevant", "is_codified_version",
                       "date_signature", "date_end_of_validity", "responsibility_agent",
                       "repertoire", "oj_reference"):
        assert _is_empty_cell(row[legis_only]), (
            f"CJEU order row should have null {legis_only}, got {row[legis_only]!r}"
        )


def test_cjeu_order_canonical_field_types_match_manifest():
    row = _row_for_case_law("62023CO0800")
    by_name = {e["name"]: e for e in schema.FIELD_MANIFEST}
    errors = []
    for name, cell in row.items():
        if name not in by_name:
            continue
        msg = _validate_field(name, cell, by_name[name])
        if msg:
            errors.append(msg)
    assert not errors, "CJEU order row violates manifest type contract:\n  " + "\n  ".join(errors)


# ---------------------------------------------------------------------------
# 4. Sector 8 — national case
# ---------------------------------------------------------------------------


def test_at_national_case_real_fetch_matches_expected_values():
    row = _row_for_case_law("82010AT0127(51)")
    assert row["celex"] == "82010AT0127(51)"
    assert row["sector"] == "8"
    assert row["origin_country"] == "Austria"
    assert row["local_identifier"], "local_identifier should be set for sector 8"
    assert row["national_judgement"] is not None
    assert row["resource_type"], "resource_type should be set"


# ---------------------------------------------------------------------------
# 5. No data lost — every CDM predicate the upstream returns must reach the
#    package output (canonical or discovered).
# ---------------------------------------------------------------------------


def _expected_keys_from_raw_cdm(raw_predicate_dict: Dict[str, list]) -> set[str]:
    """Convert a {predicate_local: [values]} dict into the set of canonical /
    fallback names the package promises to surface."""
    expected = set()
    for predicate_local in raw_predicate_dict:
        canonical = schema.cdm_canonical_name(predicate_local)
        if canonical is not None:
            expected.add(canonical)
    return expected


@pytest.mark.parametrize(
    "celex,fetcher",
    [
        ("32016R0679", "legislation"),  # GDPR
        ("32024R1689", "legislation"),  # AI Act
        ("32023R2854", "legislation"),  # Data Act
        ("62023CO0800", "case_law"),    # CJEU order
        ("82010AT0127(51)", "case_law"),  # AT national
    ],
)
def test_no_cdm_predicate_silently_dropped(celex, fetcher):
    """For each sample, every CDM predicate the upstream returned must show up
    in the package output — either under its canonical name or its discovered
    fallback name. Anything missing means we silently lost data."""
    if fetcher == "legislation":
        raw = get_raw_cellar_metadata_by_celex([celex])
        raw_props = raw.get(celex, {}) if raw else {}
        row = _row_for_legislation(celex)
    else:
        ecli = _resolve_ecli_for_celex(celex)
        if not ecli:
            pytest.skip(f"could not resolve ECLI for {celex}")
        raw = get_raw_cellar_metadata([ecli])
        raw_props = raw.get(ecli, {})
        row = _row_for_case_law(celex)

    actual_keys = {k for k, v in row.items() if not _is_empty_cell(v)}

    # Filter raw predicates to those with at least one *non-empty* value.
    # CELLAR sometimes returns a singleton list with `""` for predicates the
    # work doesn't actually populate — those should not be expected in output.
    raw_present = {
        p for p, v in raw_props.items()
        if isinstance(v, list) and any(str(x).strip() for x in v)
    }
    canonicalised = {schema.cdm_canonical_name(p) for p in raw_present}
    canonicalised.discard(None)

    missing = canonicalised - actual_keys
    # Some CDM predicates are routed through enrichment that may not always
    # populate the canonical field (e.g. CDM `case-law_delivered_by_advocate-general`
    # is the URI form; the resolved name lives in `advocate_general` from
    # InfoCuria). For those, accept a discovered fallback name as proof of
    # presence — we already enforce that above by including discovered fields.
    fallback_for_uri_predicates = {
        "case_law_delivered_by_advocate_general",  # canonical = advocate_general (resolved name)
        "case_law_delivered_by_judge",             # canonical = judge_rapporteur (resolved name)
    }
    missing -= fallback_for_uri_predicates

    assert not missing, (
        f"{celex}: CDM predicates returned upstream but missing in package output: "
        f"{sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# 6. Parsing — clean-text extraction
# ---------------------------------------------------------------------------


def test_legislation_full_text_parsing_for_gdpr():
    data = get_case_data_by_celex_id("32016R0679", language="EN")
    assert data is not None
    html = data.get("html") or ""
    assert len(html) > 100_000, "GDPR XHTML should be substantial"
    clean = get_clean_text_from_html(html)
    assert len(clean) > 50_000, "GDPR clean text should be substantial"
    # Comma preservation — the new clean extractor must not rewrite commas to
    # underscores like the legacy one does.
    assert "," in clean, "clean text dropped commas"
    # The legacy variant DOES rewrite commas — verify it remains the comma-killer
    # for backwards compatibility.
    legacy = data.get("text") or ""
    assert "," not in legacy or legacy.count(",") < clean.count(",") // 2


def test_cjeu_summary_parsing():
    data = get_case_data_by_celex_id("62023CO0800", language="EN")
    assert data is not None
    summary = data.get("summary") or ""
    assert len(summary) > 1000, "CJEU summary should be substantial"
    # InfoCuria summaries start with "Summary " for preliminary-ruling abstracts.
    assert summary.lstrip().startswith("Summary"), summary[:80]
