import json
import pytest

import pandas as pd

from cellar_extractor import fulltext_saving


def _mock_scrapers(monkeypatch):
    monkeypatch.setattr(fulltext_saving, "get_case_data_by_celex_id", lambda _id, language="EN": None)
    monkeypatch.setattr(
        fulltext_saving,
        "get_html_text_by_celex_id",
        lambda _id: "<html><body>Text body</body></html>",
    )
    monkeypatch.setattr(
        fulltext_saving,
        "get_summary_html",
        lambda _id: "<html><body>Summary</body></html>",
    )
    monkeypatch.setattr(fulltext_saving, "get_keywords_from_html", lambda html, start: "kw1;kw2")
    monkeypatch.setattr(fulltext_saving, "get_summary_from_html", lambda html, start: "summary")
    monkeypatch.setattr(
        fulltext_saving,
        "get_entire_page",
        lambda _id: "<html><body>entire page</body></html>",
    )
    monkeypatch.setattr(fulltext_saving, "get_full_text_from_html", lambda html: html)
    monkeypatch.setattr(fulltext_saving, "get_codes", lambda text: "1.1.1")
    monkeypatch.setattr(fulltext_saving, "get_eurovoc", lambda text: "eurovoc")
    monkeypatch.setattr(
        fulltext_saving,
        "get_advocate_or_judge",
        lambda text, phrase: "Adv" if "Advocate" in phrase else "Judge",
    )
    monkeypatch.setattr(fulltext_saving, "get_case_affecting", lambda text: ("62000CJ0001", "extra"))
    monkeypatch.setattr(
        fulltext_saving,
        "get_citations_with_extra_info",
        lambda text: "62000CJ0002-extra",
    )


def test_add_sections_supports_non_default_index(monkeypatch):
    _mock_scrapers(monkeypatch)
    data = pd.DataFrame(
        {
            "CELEX IDENTIFIER": ["62000CJ0001", "62000CJ0002", "62000CJ0003"],
            "ECLI": ["E1", "E2", "E3"],
        },
        index=[10, 11, 12],
    )

    fulltext = fulltext_saving.add_sections(data, threads=2)

    assert len(fulltext) == 3
    assert set(data["celex_summary"].dropna().unique()) == {"summary"}
    assert set(data["celex_keywords"].dropna().unique()) == {"kw1;kw2"}


def test_add_sections_writes_valid_json_file_with_multiple_threads(monkeypatch, tmp_path):
    _mock_scrapers(monkeypatch)
    data = pd.DataFrame(
        {
            "CELEX IDENTIFIER": [f"62000CJ{i:04d}" for i in range(12)],
            "ECLI": [f"E{i}" for i in range(12)],
        }
    )
    output_file = tmp_path / "fulltext.json"

    fulltext_saving.add_sections(data, threads=4, output_path=str(output_file))

    written = json.loads(output_file.read_text(encoding="utf-8"))
    assert isinstance(written, list)
    assert len(written) == 12


def test_add_sections_in_memory_does_not_create_files(monkeypatch, tmp_path):
    _mock_scrapers(monkeypatch)
    data = pd.DataFrame(
        {
            "CELEX IDENTIFIER": ["62000CJ0001"],
            "ECLI": ["E1"],
        }
    )

    fulltext = fulltext_saving.add_sections(data, threads=1)

    assert len(fulltext) == 1
    assert list(tmp_path.iterdir()) == []


def test_add_sections_json_filepath_alias_warns_and_writes(monkeypatch, tmp_path):
    _mock_scrapers(monkeypatch)
    data = pd.DataFrame(
        {
            "CELEX IDENTIFIER": ["62000CJ0001"],
            "ECLI": ["E1"],
        }
    )
    output_file = tmp_path / "nested" / "fulltext.json"

    with pytest.warns(DeprecationWarning, match="output_path"):
        fulltext_saving.add_sections(data, threads=1, json_filepath=str(output_file))

    assert output_file.exists()


def test_add_sections_marks_missing_reasons_for_empty_infocuria_fields(monkeypatch):
    monkeypatch.setattr(
        fulltext_saving,
        "get_case_data_by_celex_id",
        lambda _id, language="EN": {
            "text": "",
            "html": "",
            "summary": "",
            "keywords": "",
            "eurovoc": "",
            "directory_codes": "",
            "advocate": "",
            "judge": "",
            "affecting_ids": "",
            "affecting_strings": "",
            "citations_extra": "",
            "text_source": "",
            "summary_source": "",
            "missing_reasons": "UNAVAILABLE_UPSTREAM",
        },
    )
    data = pd.DataFrame({"CELEX IDENTIFIER": ["82010AT0127(51)"], "ECLI": ["E1"]})

    fulltext = fulltext_saving.add_sections(data, threads=1)

    assert data.loc[0, "celex_summary"] == ""
    reasons = data.loc[0, "missing_reasons"]
    assert "FULLTEXT_UNAVAILABLE_UPSTREAM" in reasons
    assert "SUMMARY_UNAVAILABLE_UPSTREAM" in reasons
    assert fulltext[0]["text"] == ""
