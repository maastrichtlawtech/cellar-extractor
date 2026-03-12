import pandas as pd

from cellar_extractor import cellar_extra_extract


def test_extra_cellar_always_adds_citations_before_sections(monkeypatch):
    data = pd.DataFrame({"ECLI": ["E1"], "CELEX IDENTIFIER": ["62025CJ0001"]})
    calls = []

    def _fake_add_citations(frame, threads):
        calls.append(("citations", threads, list(frame.columns)))
        frame["citing"] = ["OUT"]
        frame["cited_by"] = ["IN"]

    def _fake_add_sections(frame, threads, json_filepath=None):
        calls.append(("sections", threads, list(frame.columns), json_filepath))
        return [{"celex": "62025CJ0001", "text": "x"}]

    monkeypatch.setattr(cellar_extra_extract, "add_citations_separate", _fake_add_citations)
    monkeypatch.setattr(cellar_extra_extract, "add_sections", _fake_add_sections)

    enriched, fulltext = cellar_extra_extract.extra_cellar(data=data.copy(), threads=3)

    assert calls[0] == ("citations", 3, ["ECLI", "CELEX IDENTIFIER"])
    assert calls[1][0] == "sections"
    assert "citing" in enriched.columns
    assert "cited_by" in enriched.columns
    assert fulltext == [{"celex": "62025CJ0001", "text": "x"}]


def test_extra_cellar_ignores_legacy_webservice_credentials(monkeypatch, caplog):
    data = pd.DataFrame({"ECLI": ["E1"], "CELEX IDENTIFIER": ["62025CJ0001"]})
    caplog.set_level("INFO")

    monkeypatch.setattr(
        cellar_extra_extract,
        "add_citations_separate",
        lambda frame, threads: frame.assign(citing=[""], cited_by=[""]),
    )
    monkeypatch.setattr(
        cellar_extra_extract,
        "add_sections",
        lambda frame, threads, json_filepath=None: [],
    )

    cellar_extra_extract.extra_cellar(
        data=data,
        threads=1,
        username="legacy-user",
        password="legacy-pass",
    )

    assert "ignored" in caplog.text
