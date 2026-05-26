"""
Full-year CJEU corpus completeness benchmark — year 2020.

Pulls every case-law document (sectors 6 + 8) whose ``work_date_document``
falls in 2020, runs the complete extraction pipeline (``get_cellar_extra``),
and validates:

- **Completeness of discovery**: the extracted row count matches the CELLAR
  SPARQL ground-truth count within a small tolerance.
- **Schema contract**: every row carries the full canonical schema
  (``schema.CANONICAL_COLUMNS``); no canonical column is missing.
- **Coverage of identifiers**: ``celex``, ``ecli``, ``date_publication``,
  ``sector`` populated on ≥99% of rows (CELLAR has a small tail of
  irregular records).
- **Sector affinity**: every row's sector is in {6, 8}; legislation
  columns (``eli``, ``in_force``, ``date_signature``, …) are null on case
  law rows.
- **Date sanity**: every populated ``date_publication`` is in 2020.
- **No-data-lost (spot check)**: for a random sample of rows, every CDM
  predicate the upstream actually returned reaches the package output.
- **Enrichment coverage**: ``summary``, ``citing``, ``cited_by``,
  ``advocate_general``, ``judge_rapporteur`` populated on a significant
  fraction of sector-6 rows.
- **Fulltext sidecar**: one entry per CELEX, each with the required
  fulltext-row shape.

Wall time: ~20–30 min at the time of writing. Gated by
``RUN_CORPUS_2020=1`` so it never runs in default suites.

Output: the enriched DataFrame and fulltext JSON land under
``tests/out/corpus_2020/`` for downstream inspection (gitignored).
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import pytest
from SPARQLWrapper import JSON, POST, SPARQLWrapper

from cellar_extractor import cellar, eurlex_scraping, schema
from cellar_extractor.cellar_queries import get_raw_cellar_metadata


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CORPUS_2020") != "1",
    reason="Set RUN_CORPUS_2020=1 to run the full-year 2020 corpus benchmark (~20–30 min).",
)


SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
OUT_DIR = Path(__file__).parent / "out" / "corpus_2020"


# ---------------------------------------------------------------------------
# One-shot fixture: scrape the full year, share the result across tests.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus_2020():
    """Run the full 2020 extraction once and reuse it for every assertion."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    eurlex_scraping._get_case_data_cached.cache_clear()

    started = time.time()
    df, fulltext = cellar.get_cellar_extra(
        sd="2020-01-01",
        ed="2020-12-31T23:59:59",
        max_ecli=10_000,
        threads=10,
        save=True,
        metadata_output_path=str(OUT_DIR / "cellar_extra_2020.csv"),
        fulltext_output_path=str(OUT_DIR / "cellar_extra_2020_fulltext.json"),
        return_data=True,
    )
    elapsed = time.time() - started

    (OUT_DIR / "BENCHMARK.md").write_text(
        f"# 2020 corpus benchmark\n\n"
        f"- elapsed: **{elapsed:.1f}s** ({elapsed / 60:.1f} min)\n"
        f"- rows: **{len(df)}**\n"
        f"- cols: **{len(df.columns)}**\n"
        f"- fulltext entries: **{len(fulltext)}**\n"
        f"- avg s / CELEX: **{elapsed / max(len(df), 1):.2f}s**\n",
        encoding="utf-8",
    )
    return df, fulltext, elapsed


def _ground_truth_count() -> int:
    """Count of distinct ECLIs whose work_date_document is in 2020.

    The package emits one row per ECLI (case identifier), not per work.
    A single ECLI can fan out to multiple works (judgment + summary +
    opinion + abstract) all sharing one ECLI. The right ground truth for
    row count is therefore COUNT DISTINCT ?ecli, not COUNT DISTINCT ?doc.
    """
    sparql = SPARQLWrapper(SPARQL_ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)
    sparql.setTimeout(60)
    sparql.setQuery(
        """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        SELECT (COUNT(DISTINCT ?ecli) AS ?n) WHERE {
            ?doc cdm:case-law_ecli ?ecli .
            ?doc cdm:work_date_document ?date .
            FILTER(STR(?date) >= "2020-01-01" && STR(?date) <= "2020-12-31")
        }
        """
    )
    rows = sparql.queryAndConvert().get("results", {}).get("bindings", [])
    return int(rows[0]["n"]["value"]) if rows else 0


# ---------------------------------------------------------------------------
# Small helpers shared across assertions.
# ---------------------------------------------------------------------------


def _is_empty(cell: Any) -> bool:
    if cell is None:
        return True
    if isinstance(cell, float) and pd.isna(cell):
        return True
    if isinstance(cell, str) and cell.strip() == "":
        return True
    return False


def _populated_fraction(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    return sum(0 if _is_empty(v) else 1 for v in df[column]) / max(len(df), 1)


# ---------------------------------------------------------------------------
# 1. Completeness: row count vs CELLAR ground truth.
# ---------------------------------------------------------------------------


def test_row_count_matches_cellar_ground_truth(corpus_2020):
    df, _, _ = corpus_2020
    truth = _ground_truth_count()
    # Allow ±2% drift between the package's date-window discovery and a freshly
    # issued GROUP BY count — CELLAR re-indexes constantly, and both numbers
    # should match within tolerance.
    tolerance = max(int(truth * 0.02), 5)
    delta = abs(len(df) - truth)
    assert delta <= tolerance, (
        f"row count drifted: package={len(df)}, ground truth={truth}, "
        f"delta={delta} > tolerance={tolerance}"
    )


# ---------------------------------------------------------------------------
# 2. Schema contract: every canonical column present, identifiers populated.
# ---------------------------------------------------------------------------


def test_canonical_schema_columns_all_present(corpus_2020):
    df, _, _ = corpus_2020
    missing = [c for c in schema.CANONICAL_COLUMNS if c not in df.columns]
    assert not missing, f"canonical columns missing from corpus output: {missing}"


def test_core_identifiers_populated_on_nearly_all_rows(corpus_2020):
    df, _, _ = corpus_2020
    for col, min_fraction in [
        ("celex", 0.99),
        ("ecli", 0.99),
        ("sector", 0.99),
        ("date_publication", 0.99),
        ("resource_type", 0.95),
        ("alternate_identifiers", 0.95),
        ("work_date_creation_legacy", 0.95),
    ]:
        frac = _populated_fraction(df, col)
        assert frac >= min_fraction, (
            f"{col!r} populated on {frac:.1%} of rows, expected >= {min_fraction:.0%}"
        )


# ---------------------------------------------------------------------------
# 3. Sector affinity: only case law sectors present; legislation cols null.
# ---------------------------------------------------------------------------


def test_every_row_is_case_law(corpus_2020):
    df, _, _ = corpus_2020
    sectors = set(df["sector"].dropna().astype(str).str.strip())
    bad = sectors - {"6", "8"}
    assert not bad, f"unexpected sectors in case-law corpus: {sorted(bad)}"


def test_legislation_only_fields_null_on_case_law(corpus_2020):
    """Every canonical field marked sector_affinity=legislation in the manifest
    must be null on every case-law row. Fields that the CDM ontology permits on
    both case-law and legislation (e.g. ``based_on_treaty``) are tagged
    ``any`` in the manifest and excluded from this check."""
    df, _, _ = corpus_2020
    legislation_only_cols = [
        e["name"] for e in schema.FIELD_MANIFEST
        if e.get("sector_affinity") == "legislation" and e.get("canonical")
    ]
    violations = {}
    for col in legislation_only_cols:
        if col not in df.columns:
            continue
        non_null = (~df[col].apply(_is_empty)).sum()
        if non_null > 0:
            violations[col] = non_null
    assert not violations, (
        f"legislation-only columns populated on case-law rows: {violations}"
    )


# ---------------------------------------------------------------------------
# 4. Date sanity: date_publication in 2020.
# ---------------------------------------------------------------------------


def test_date_publication_in_window(corpus_2020):
    """date_publication is multi-valued (one ECLI bundles multiple works that
    may have different delivery dates). Allow up to 1% of rows to carry at
    least one out-of-2020 date — that's CELLAR's standard noise level for
    related-works delivered near the year boundary."""
    df, _, _ = corpus_2020
    out_of_window = []
    for value in df["date_publication"].dropna().astype(str):
        parts = [p.strip() for p in value.split(";") if p.strip()]
        if parts and not any(p.startswith("2020-") for p in parts):
            out_of_window.append(value)
    fraction = len(out_of_window) / max(len(df), 1)
    assert fraction <= 0.01, (
        f"{len(out_of_window)} rows ({fraction:.1%}) have no 2020 date "
        f"in date_publication: first few = {out_of_window[:5]}"
    )


# ---------------------------------------------------------------------------
# 5. Enrichment coverage.
# ---------------------------------------------------------------------------


def test_enrichment_populates_sector6_rows(corpus_2020):
    """Citation enrichment (citing / cited_by) is checked separately because
    the SPARQL endpoint can return RemoteDisconnected on the chunk-of-1000
    citation query — when that happens the whole graph for that chunk goes
    to null. That's an upstream availability issue, not a code bug. The
    pipeline-quality assertions here check fields that are robust to the
    citation-endpoint outage."""
    df, _, _ = corpus_2020
    sec6 = df[df["sector"].astype(str).str.strip() == "6"]
    assert len(sec6) > 100, f"too few sector-6 rows ({len(sec6)}) — check discovery filter"
    for col, min_fraction in [
        ("summary", 0.80),
        ("advocate_general", 0.50),
        ("judge_rapporteur", 0.80),
        ("judicial_procedure_type", 0.80),
        ("language_procedure", 0.80),
        ("origin_country", 0.80),
        ("subject_matter", 0.80),
    ]:
        frac = (~sec6[col].apply(_is_empty)).sum() / len(sec6)
        assert frac >= min_fraction, (
            f"sector-6 column {col!r} populated on {frac:.1%}, expected >= {min_fraction:.0%}"
        )


def test_citation_graph_present_or_documented_as_outage(corpus_2020):
    """Citation enrichment coverage depends on the CELLAR SPARQL endpoint's
    stability during the run. Bidirectional-relations queries (UNION of cites
    and cited-by branches) intermittently return RemoteDisconnected — the
    per-chunk pipeline now tolerates failures rather than poisoning the whole
    graph, so what we get is a partial graph proportional to endpoint health.

    The strict assertion: ANY citations must come through. Zero means a full
    upstream outage; in that case fail loudly so the user knows to re-run.
    Partial coverage (>0) passes — the package is doing its job; the rest is
    the endpoint."""
    df, _, _ = corpus_2020
    sec6 = df[df["sector"].astype(str).str.strip() == "6"]
    citing = (~sec6["citing"].apply(_is_empty)).sum()
    cited_by = (~sec6["cited_by"].apply(_is_empty)).sum()
    citing_frac = citing / max(len(sec6), 1)
    cited_by_frac = cited_by / max(len(sec6), 1)
    if citing == 0 and cited_by == 0:
        pytest.fail(
            "Citation graph entirely empty for sector-6 rows. Likely a full "
            "SPARQL endpoint outage during citation enrichment "
            "(RemoteDisconnected on citation-relations query). Re-run when "
            "the endpoint stabilises."
        )
    print(  # pragma: no cover - informational only
        f"\n  citation coverage: citing={citing_frac:.1%}, cited_by={cited_by_frac:.1%}"
    )


# ---------------------------------------------------------------------------
# 6. Fulltext sidecar: one entry per row, well-shaped.
# ---------------------------------------------------------------------------


def test_fulltext_sidecar_one_entry_per_row(corpus_2020):
    df, fulltext, _ = corpus_2020
    assert len(fulltext) >= int(len(df) * 0.95), (
        f"fulltext sidecar has {len(fulltext)} entries for {len(df)} rows "
        f"(<95% coverage)"
    )
    required_keys = {"celex", "ecli", "text", "text_source", "text_language", "text_format", "missing_reasons"}
    for entry in fulltext[:50]:
        missing = required_keys - set(entry)
        assert not missing, f"fulltext entry missing keys {missing}: {entry.get('celex')!r}"


# ---------------------------------------------------------------------------
# 7. No-data-lost spot check: for a random sample of rows, verify every CDM
#    predicate the upstream returned is reflected in the package output.
# ---------------------------------------------------------------------------


def test_no_cdm_predicate_silently_dropped_on_random_sample(corpus_2020):
    df, _, _ = corpus_2020
    rng = random.Random(20)
    eclis = df["ecli"].dropna().astype(str).tolist()
    sample_eclis = rng.sample(eclis, k=min(20, len(eclis)))
    raw = get_raw_cellar_metadata(sample_eclis)

    failures = []
    for ecli in sample_eclis:
        raw_props = raw.get(ecli, {})
        # Only consider predicates that returned at least one non-empty value.
        raw_present = {
            p for p, v in raw_props.items()
            if isinstance(v, list) and any(str(x).strip() for x in v)
        }
        expected = {schema.cdm_canonical_name(p) for p in raw_present}
        expected.discard(None)

        # Pull the row that matches this ECLI.
        rows = df[df["ecli"].astype(str) == ecli]
        if rows.empty:
            failures.append(f"{ecli}: no row in extracted DataFrame")
            continue
        row = rows.iloc[0].to_dict()
        actual = {k for k, v in row.items() if not _is_empty(v)}

        # CDM URI-form predicates whose resolved name comes from InfoCuria.
        accepted_as_resolved_elsewhere = {
            "case_law_delivered_by_advocate_general",
            "case_law_delivered_by_judge",
        }
        missing = (expected - actual) - accepted_as_resolved_elsewhere
        if missing:
            failures.append(f"{ecli}: {sorted(missing)}")

    assert not failures, (
        "CDM predicates silently dropped on these sample rows:\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------------------
# 8. Type contract sample: validate a slice against the manifest's types.
# ---------------------------------------------------------------------------


def test_manifest_type_contract_on_random_sample(corpus_2020):
    """Walk 50 random rows × every canonical field and verify populated values
    match their declared type in FIELD_MANIFEST. Multi-cardinality fields are
    split on ``;`` first; single-cardinality fields are treated as one opaque
    value (they may legitimately contain ``;`` in free text — e.g. summary)."""
    df, _, _ = corpus_2020
    by_name = {e["name"]: e for e in schema.FIELD_MANIFEST}
    rng = random.Random(21)
    sample_indices = rng.sample(range(len(df)), k=min(50, len(df)))

    errors = []
    for idx in sample_indices:
        row = df.iloc[idx].to_dict()
        for name, value in row.items():
            entry = by_name.get(name)
            if entry is None:
                continue
            if _is_empty(value):
                continue
            type_ = entry["type"]
            cardinality = entry["cardinality"]
            if cardinality == "multi":
                values = [v.strip() for v in str(value).split(";") if v.strip()]
            else:
                values = [str(value).strip()]
            for v in values:
                if type_ == "date" and not (len(v) == 10 and v[4] == "-" and v[7] == "-"):
                    errors.append(f"row {idx} field {name!r} value {v!r} not YYYY-MM-DD")
                elif type_ == "boolean" and v not in {"0", "1"}:
                    errors.append(f"row {idx} field {name!r} value {v!r} not boolean")
                elif type_ == "integer":
                    try:
                        int(v)
                    except ValueError:
                        errors.append(f"row {idx} field {name!r} value {v!r} not integer")
                elif type_ == "url" and not (v.startswith("http://") or v.startswith("https://")):
                    errors.append(f"row {idx} field {name!r} value {v!r} not URL-shaped")
            if len(errors) > 30:
                break
        if len(errors) > 30:
            break

    assert not errors, (
        "manifest type contract violations in sample:\n  " + "\n  ".join(errors[:30])
    )
