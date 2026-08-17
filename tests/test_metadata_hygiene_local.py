"""Local tests for metadata hygiene fixes:

1. keywords / eurovoc are no longer aliased copies of subject-matter labels
   on the CELLAR-backed case-data paths (sector 8 and the sector-6 fallback).
2. The literal CELLAR curation placeholder ("Provisional data") is dropped
   at the metadata assembly point, in both the celex- and ecli-keyed loops.
"""

import cellar_extractor.cellar_queries as cq
import cellar_extractor.eurlex_scraping as es


def _fake_fulltexts(*_a, **_k):
    return [
        {
            "text": "judgment body",
            "html": "<pre>judgment body</pre>",
            "text_source": "CELLAR_ITEM",
            "text_language": "EN",
            "text_format": "xhtml",
        }
    ]


def test_sector8_keywords_and_eurovoc_stay_empty(monkeypatch):
    monkeypatch.setattr(es, "_fetch_sector8_work_uri", lambda *a, **k: "http://cellar/w")
    monkeypatch.setattr(
        es, "_fetch_sector8_work_uris", lambda *a, **k: ["http://cellar/w"]
    )
    monkeypatch.setattr(es, "_fetch_sector8_items_for_work", lambda *a, **k: [])
    monkeypatch.setattr(es, "_fanout_fulltexts_from_candidates", _fake_fulltexts)
    monkeypatch.setattr(es, "_fetch_sector8_summary_work_uris", lambda *a, **k: [])
    monkeypatch.setattr(
        es,
        "_fetch_sector8_subject_labels",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    data = es._get_case_data_sector8("82024TX0001")
    assert data["keywords"] == ""
    assert data["eurovoc"] == ""
    assert data["text"] == "judgment body"


def test_sector6_fallback_keywords_and_eurovoc_stay_empty(monkeypatch):
    monkeypatch.setattr(es, "_fetch_sector8_work_uri", lambda *a, **k: "http://cellar/w")
    monkeypatch.setattr(
        es, "_fetch_sector8_work_uris", lambda *a, **k: ["http://cellar/w"]
    )
    monkeypatch.setattr(es, "_fetch_sector8_items_for_work", lambda *a, **k: [{}])
    monkeypatch.setattr(es, "_fanout_fulltexts_from_candidates", _fake_fulltexts)
    monkeypatch.setattr(
        es,
        "_fetch_sector8_subject_labels",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    data = es._get_case_data_sector6_cellar_fallback("61964CJ0006")
    assert data["keywords"] == ""
    assert data["eurovoc"] == ""
    assert data["text"] == "judgment body"


def _bindings_response(key_field, key_value):
    def binding(pred, value, label=None):
        b = {
            key_field: {"value": key_value},
            "p": {"value": f"http://publications.europa.eu/ontology/cdm#{pred}"},
            "o": {"value": value},
        }
        if label is not None:
            b["olabel"] = {"value": label}
        return b

    return {
        "results": {
            "bindings": [
                binding("case_law_is_about_concept_case_law", "Provisional data"),
                binding(
                    "case_law_is_about_concept_case_law",
                    "uri://c1",
                    label="Provisional data",
                ),
                binding("case_law_is_about_concept_case_law", "Similarity between marks"),
                binding("work_cites_work", "http://pub/res/abc"),
            ]
        }
    }


def test_placeholder_filtered_in_celex_metadata(monkeypatch):
    monkeypatch.setattr(
        cq,
        "_query_with_retries",
        lambda *a, **k: _bindings_response("celex", "62024CJ0001"),
    )
    out = cq.get_raw_cellar_metadata_by_celex(["62024CJ0001"])
    values = out["62024CJ0001"].get("case_law_is_about_concept_case_law", [])
    assert values == ["Similarity between marks"]
    assert out["62024CJ0001"]["work_cites_work"] == ["http://pub/res/abc"]


def test_placeholder_filtered_in_ecli_metadata(monkeypatch):
    monkeypatch.setattr(
        cq,
        "_query_with_retries",
        lambda *a, **k: _bindings_response("ecli", "ECLI:EU:C:2024:1"),
    )
    out = cq.get_raw_cellar_metadata(["ECLI:EU:C:2024:1"])
    values = out["ECLI:EU:C:2024:1"].get("case_law_is_about_concept_case_law", [])
    assert values == ["Similarity between marks"]


def test_items_for_celex_unions_across_all_works(monkeypatch):
    """A CELEX can map to several CELLAR works with different language
    coverage (observed live: a 2-language partial edition next to a
    22-language sibling). Candidates must be the union across all works,
    deduplicated on (language, format, item_url) — picking one work
    arbitrarily is how nine sampled judgments lost their English texts."""
    works = {
        "http://cellar/w-sparse": [
            {"item_url": "u_de", "format": "xhtml", "language": "DE"},
            {"item_url": "u_fr", "format": "xhtml", "language": "FR"},
        ],
        "http://cellar/w-full": [
            {"item_url": "u_de", "format": "xhtml", "language": "DE"},  # dup
            {"item_url": "u_en", "format": "xhtml", "language": "EN"},
            {"item_url": "u_nl", "format": "xhtml", "language": "NL"},
        ],
    }
    monkeypatch.setattr(es, "_fetch_sector8_work_uris", lambda *a, **k: list(works))
    monkeypatch.setattr(es, "_fetch_sector8_items_for_work", lambda uri: works[uri])
    uris, cands = es._fetch_sector8_items_for_celex("62006CJ0005", sector="6")
    assert len(uris) == 2
    langs = sorted(c["language"] for c in cands)
    assert langs == ["DE", "EN", "FR", "NL"]  # union, DE deduped
