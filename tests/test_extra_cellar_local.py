import pandas as pd
import pytest

from cellar_extractor import cellar_extra_extract


def test_extra_cellar_always_adds_citations_before_sections(monkeypatch):
    data = pd.DataFrame({"ECLI": ["E1"], "CELEX IDENTIFIER": ["62025CJ0001"]})
    calls = []

    def _fake_add_citations(frame, threads):
        calls.append(("citations", threads, list(frame.columns)))
        frame["citing"] = ["OUT"]
        frame["cited_by"] = ["IN"]

    def _fake_add_sections(frame, threads, output_path=None, json_filepath=None, fulltext_output_path=None):
        calls.append(("sections", threads, list(frame.columns), output_path, json_filepath, fulltext_output_path))
        return [{"celex": "62025CJ0001", "text": "x"}]

    monkeypatch.setattr(cellar_extra_extract, "add_citations_separate", _fake_add_citations)
    monkeypatch.setattr(cellar_extra_extract, "add_sections", _fake_add_sections)

    enriched, fulltext = cellar_extra_extract.extra_cellar(data=data.copy(), threads=3)

    assert calls[0] == ("citations", 3, ["ECLI", "CELEX IDENTIFIER"])
    assert calls[1][0] == "sections"
    assert "citing" in enriched.columns
    assert "cited_by" in enriched.columns
    assert fulltext == [{"celex": "62025CJ0001", "text": "x"}]


def test_extra_cellar_writes_metadata_and_fulltext_to_explicit_paths(monkeypatch, tmp_path):
    data = pd.DataFrame({"ECLI": ["E1"], "CELEX IDENTIFIER": ["62025CJ0001"]})

    monkeypatch.setattr(
        cellar_extra_extract,
        "add_citations_separate",
        lambda frame, threads: frame.assign(citing=[""], cited_by=[""]),
    )
    monkeypatch.setattr(
        cellar_extra_extract,
        "add_sections",
        lambda frame, threads, output_path=None, json_filepath=None, fulltext_output_path=None: [
            {"celex": "62025CJ0001", "path": str(output_path)}
        ],
    )

    metadata_path = tmp_path / "meta.csv"
    fulltext_path = tmp_path / "fulltext.json"
    enriched, fulltext = cellar_extra_extract.extra_cellar(
        data=data.copy(),
        threads=1,
        metadata_output_path=str(metadata_path),
        fulltext_output_path=str(fulltext_path),
    )

    assert metadata_path.exists()
    assert fulltext == [{"celex": "62025CJ0001", "path": str(fulltext_path)}]
    assert "CELEX IDENTIFIER" in enriched.columns


def test_extra_cellar_input_path_uses_derived_output_paths_without_cwd_side_effects(
    monkeypatch, tmp_path
):
    input_path = tmp_path / "inputs" / "cases.csv"
    input_path.parent.mkdir(parents=True)
    pd.DataFrame({"ECLI": ["E1"], "CELEX IDENTIFIER": ["62025CJ0001"]}).to_csv(
        input_path, index=False
    )
    seen = {}

    monkeypatch.setattr(
        cellar_extra_extract,
        "add_citations_separate",
        lambda frame, threads: frame.assign(citing=[""], cited_by=[""]),
    )

    def _fake_add_sections(frame, threads, output_path=None, json_filepath=None, fulltext_output_path=None):
        seen["output_path"] = output_path
        return [{"celex": "62025CJ0001"}]

    monkeypatch.setattr(cellar_extra_extract, "add_sections", _fake_add_sections)

    enriched, fulltext = cellar_extra_extract.extra_cellar(
        input_path=str(input_path),
        threads=1,
    )

    assert enriched.loc[0, "CELEX IDENTIFIER"] == "62025CJ0001"
    assert fulltext == [{"celex": "62025CJ0001"}]
    assert input_path.exists()
    assert (tmp_path / "inputs" / "cases_fulltext.json").exists() is False
    assert seen["output_path"] == str(tmp_path / "inputs" / "cases_fulltext.json")
    assert not (tmp_path / "json").exists()
    assert not (tmp_path / "csv").exists()
    assert not (tmp_path / "txt").exists()


def test_extra_cellar_filepath_alias_emits_deprecation_warning(monkeypatch, tmp_path):
    input_path = tmp_path / "cases.csv"
    pd.DataFrame({"ECLI": ["E1"], "CELEX IDENTIFIER": ["62025CJ0001"]}).to_csv(
        input_path, index=False
    )
    monkeypatch.setattr(
        cellar_extra_extract,
        "add_citations_separate",
        lambda frame, threads: frame.assign(citing=[""], cited_by=[""]),
    )
    monkeypatch.setattr(
        cellar_extra_extract,
        "add_sections",
        lambda frame, threads, output_path=None, json_filepath=None, fulltext_output_path=None: [],
    )

    with pytest.warns(DeprecationWarning, match="input_path"):
        cellar_extra_extract.extra_cellar(filepath=str(input_path), threads=1)


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
        lambda frame, threads, output_path=None, json_filepath=None, fulltext_output_path=None: [],
    )

    cellar_extra_extract.extra_cellar(
        data=data,
        threads=1,
        username="legacy-user",
        password="legacy-pass",
    )

    assert "ignored" in caplog.text
