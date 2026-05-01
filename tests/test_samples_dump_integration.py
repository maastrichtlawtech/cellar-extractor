"""
Live samples-dump integration test.

Fetches a curated set of CELEX documents covering multiple sectors and writes
the resulting full text, raw markup, summary, and metadata under tests/out/
for human inspection.

For each sample we dump:
  - metadata.json           per-CELEX dispatch dict (slim view)
  - metadata_full.json      enriched record from the full pipeline (rich view)
  - text.txt                "clean" plain text (no comma-to-underscore)
  - text_legacy.txt         comma-to-underscore variant produced by the
                            existing CSV pipeline (only when it differs)
  - document.{xhtml,html}   raw markup
  - summary.txt             summary text when available

Run with:

    RUN_SAMPLES_DUMP=1 pytest -q tests/test_samples_dump_integration.py
"""

import json
import os
import re
from pathlib import Path

import pandas as pd
import pytest
from SPARQLWrapper import JSON, POST, SPARQLWrapper

from cellar_extractor import eurlex_scraping
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
from cellar_extractor.schema import CANONICAL_COLUMNS, fill_canonical


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SAMPLES_DUMP") != "1",
    reason="Set RUN_SAMPLES_DUMP=1 to fetch live samples and dump them under tests/out/.",
)


OUT_DIR = Path(__file__).parent / "out"


SAMPLES = [
    # (sector, celex, label, expect_text)
    ("3", "32016R0679", "GDPR (Regulation 2016/679)", True),
    ("3", "32024R1689", "EU AI Act (Regulation 2024/1689)", True),
    ("3", "32023R2854", "Data Act (Regulation 2023/2854)", True),
    ("0", "02002L0058-20091219", "ePrivacy Directive (consolidated)", True),
    ("6", "62023CO0800", "CJEU order (sector 6, with indexed citations)", True),
    ("8", "82010AT0127(51)", "Austrian national case (sector 8, full data)", True),
    ("8", "81994FR0111(01)", "French national case (sector 8, unavailable upstream)", False),
]


def _resolve_ecli_for_celex(celex):
    """Resolve a case-law CELEX to its ECLI via CELLAR SPARQL.

    Returns "" when the CELEX is not indexed (e.g. very recent cases that
    InfoCuria has but CELLAR has not yet ingested), so the caller can skip
    the ECLI-keyed metadata fetch instead of feeding it a stale mapping.
    """
    sparql = SPARQLWrapper("https://publications.europa.eu/webapi/rdf/sparql")
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)
    sparql.setQuery(
        """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        SELECT ?ecli WHERE {
            ?doc cdm:resource_legal_id_celex ?celex .
            ?doc cdm:case-law_ecli ?ecli .
            FILTER(STR(?celex) = "%s")
        }
        LIMIT 1
        """
        % celex.replace('"', '\\"')
    )
    try:
        ret = sparql.queryAndConvert()
    except Exception:
        return ""
    rows = ret.get("results", {}).get("bindings", []) if isinstance(ret, dict) else []
    if not rows:
        return ""
    return rows[0].get("ecli", {}).get("value", "")


@pytest.fixture(autouse=True)
def _clear_case_cache():
    eurlex_scraping._get_case_data_cached.cache_clear()
    yield
    eurlex_scraping._get_case_data_cached.cache_clear()


def _safe_dirname(celex):
    return re.sub(r"[^A-Za-z0-9._-]", "_", celex)


def _nullify_missing(record):
    """Map empty / NaN cells to JSON null but keep every key."""
    out = {}
    for key, value in record.items():
        if value is None:
            out[key] = None
        elif isinstance(value, float) and pd.isna(value):
            out[key] = None
        elif isinstance(value, str) and value == "":
            out[key] = None
        else:
            out[key] = value
    return out


def _enriched_record_for_case_law(celex, ecli):
    """Run the same pipeline that get_cellar_extra runs, but for one CELEX."""
    if not ecli:
        return None
    raw = get_raw_cellar_metadata([ecli])
    df = json_to_csv_returning(raw)
    if df is False or df is None or len(df) == 0:
        return None
    df.loc[:, "celex"] = celex
    df.loc[:, "ecli"] = ecli
    add_citations_separate(df, threads=1)
    add_sections(df, threads=1)
    record = df.iloc[0].to_dict()
    return _nullify_missing(fill_canonical(record))


def _enriched_record_for_legislation(celex):
    """Best-effort SPARQL metadata for legislation (no ECLI)."""
    raw = get_raw_cellar_metadata_by_celex([celex])
    if not raw or not raw.get(celex):
        return None
    df = json_to_csv_returning(raw)
    if df is False or df is None or len(df) == 0:
        return None
    record = df.iloc[0].to_dict()
    record["celex"] = celex
    return _nullify_missing(fill_canonical(record))


def _write_sample_dump(sector, celex, label, data, enriched):
    target = OUT_DIR / f"sector{sector}" / _safe_dirname(celex)
    target.mkdir(parents=True, exist_ok=True)

    if data is None:
        meta = {
            "celex": celex,
            "label": label,
            "result": "None (dispatch returned no data)",
        }
        (target / "metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if enriched is not None:
            (target / "metadata_full.json").write_text(
                json.dumps(enriched, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        return target

    meta = {k: v for k, v in data.items() if k not in {"html", "text", "summary"}}
    meta["celex"] = celex
    meta["label"] = label
    meta["text_chars"] = len(data.get("text") or "")
    meta["html_chars"] = len(data.get("html") or "")
    meta["summary_chars"] = len(data.get("summary") or "")

    (target / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    if enriched is not None:
        (target / "metadata_full.json").write_text(
            json.dumps(enriched, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    legacy_text = data.get("text") or ""
    html = data.get("html") or ""
    clean_text = get_clean_text_from_html(html) if html else ""
    if clean_text:
        (target / "text.txt").write_text(clean_text, encoding="utf-8")
    if legacy_text and legacy_text != clean_text:
        (target / "text_legacy.txt").write_text(legacy_text, encoding="utf-8")
    if html:
        fmt = (data.get("text_format") or "").lower()
        ext = "xhtml" if fmt in {"xhtml", "xml"} else "html"
        (target / f"document.{ext}").write_text(html, encoding="utf-8")
    summary = data.get("summary") or ""
    if summary:
        (target / "summary.txt").write_text(summary, encoding="utf-8")
    return target


@pytest.mark.parametrize(
    "sector,celex,label,expect_text",
    SAMPLES,
    ids=[f"sector{s}-{c}" for s, c, _, _ in SAMPLES],
)
def test_dump_sample(sector, celex, label, expect_text):
    data = get_case_data_by_celex_id(celex, language="EN")

    enriched = None
    if sector in {"3", "0"}:
        enriched = _enriched_record_for_legislation(celex)
    else:
        ecli = _resolve_ecli_for_celex(celex) if expect_text else ""
        enriched = _enriched_record_for_case_law(celex, ecli) if ecli else None

    target = _write_sample_dump(sector, celex, label, data, enriched)
    assert (target / "metadata.json").exists()

    if not expect_text:
        assert data is not None, f"{celex}: dispatch returned None for known-unavailable sample"
        assert "UNAVAILABLE_UPSTREAM" in data.get("missing_reasons", "")
        return

    assert data is not None, f"{celex}: dispatch returned None"
    assert data["sector"] == sector, (
        f"{celex}: expected sector {sector}, got {data['sector']!r}"
    )
    assert (data.get("text") or "") != "", f"{celex}: expected non-empty text"


def test_zz_write_index():
    """Run last (alphabetic order): build a human-readable INDEX.md."""
    if not OUT_DIR.exists():
        pytest.skip("tests/out/ was not populated")

    lines = ["# Sample dump index", ""]
    for sector_dir in sorted(OUT_DIR.glob("sector*")):
        lines.append(f"## {sector_dir.name}")
        lines.append("")
        for sample_dir in sorted(p for p in sector_dir.iterdir() if p.is_dir()):
            meta_path = sample_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            label = meta.get("label", "")
            text_chars = meta.get("text_chars", 0)
            html_chars = meta.get("html_chars", 0)
            summary_chars = meta.get("summary_chars", 0)
            text_source = meta.get("text_source", "") or "—"
            text_language = meta.get("text_language", "") or "—"
            missing = meta.get("missing_reasons", "") or "none"
            full_path = sample_dir / "metadata_full.json"
            canonical_populated = 0
            canonical_total = len(CANONICAL_COLUMNS)
            discovered_populated = 0
            if full_path.exists():
                try:
                    full = json.loads(full_path.read_text(encoding="utf-8"))
                    for k, v in full.items():
                        if v is None:
                            continue
                        if k in CANONICAL_COLUMNS:
                            canonical_populated += 1
                        else:
                            discovered_populated += 1
                except Exception:
                    pass
            lines.append(
                f"- **{sample_dir.name}** — {label}\n"
                f"  - text: {text_chars} chars (source: {text_source}, lang: {text_language})\n"
                f"  - html: {html_chars} chars\n"
                f"  - summary: {summary_chars} chars\n"
                f"  - canonical fields: {canonical_populated} / {canonical_total} populated"
                f" (+ {discovered_populated} discovered extras)\n"
                f"  - missing_reasons: `{missing}`"
            )
        lines.append("")
    (OUT_DIR / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
