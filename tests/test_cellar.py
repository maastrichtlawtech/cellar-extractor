import json
from pathlib import Path
import time

import pandas as pd

from cellar_extractor import cellar


def _base_metadata(ecli, celex):
    """Return metadata in the new URI-keyed shape produced by
    cellar_queries.get_raw_cellar_metadata."""
    return {
        ecli: {
            "case-law_ecli": [ecli],
            "resource_legal_id_celex": [celex],
            "work_date_document": ["2025-01-01"],
            "resource_legal_type": ["CJ"],
            "resource_legal_id_sector": ["6"],
        }
    }


def test_get_cellar_csv_in_memory(monkeypatch):
    monkeypatch.setattr(
        cellar,
        "get_all_eclis",
        lambda starting_date, ending_date, limit=None: ["E1", "E2"][:limit] if limit else ["E1", "E2"],
    )
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: {
            **_base_metadata("E1", "62025CJ0001"),
            **_base_metadata("E2", "62025CJ0002"),
        },
    )

    df = cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save=False,
        max_ecli=10,
        sd="2025-01-01",
        file_format="csv",
    )

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert set(df["ecli"].tolist()) == {"E1", "E2"}


def test_get_cellar_json_in_memory(monkeypatch):
    monkeypatch.setattr(cellar, "get_all_eclis", lambda starting_date, ending_date, limit=None: ["E1"])
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: _base_metadata("E1", "62025CJ0001"),
    )

    output = cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save=False,
        max_ecli=10,
        sd="2025-01-01",
        file_format="json",
    )

    assert isinstance(output, dict)
    assert output["E1"]["resource_legal_id_celex"] == ["62025CJ0001"]


def test_get_cellar_json_save_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cellar, "get_all_eclis", lambda starting_date, ending_date, limit=None: ["E1"])
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: _base_metadata("E1", "62025CJ0001"),
    )

    cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save_file="y",
        max_ecli=10,
        sd="2025-01-01",
        file_format="json",
    )

    target = Path("data/cellar_2025-01-01_2025-01-02T00_00_00.json")
    assert target.exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert "E1" in written


def test_get_cellar_in_memory_does_not_create_default_output_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cellar, "get_all_eclis", lambda starting_date, ending_date, limit=None: ["E1"])
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: _base_metadata("E1", "62025CJ0001"),
    )

    cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save=False,
        max_ecli=10,
        sd="2025-01-01",
        file_format="json",
    )

    assert not (tmp_path / "data").exists()


def test_get_cellar_save_file_supports_custom_output_path(monkeypatch, tmp_path):
    monkeypatch.setattr(cellar, "get_all_eclis", lambda starting_date, ending_date, limit=None: ["E1"])
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: _base_metadata("E1", "62025CJ0001"),
    )
    output_path = tmp_path / "exports" / "custom.csv"

    result = cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save=True,
        max_ecli=10,
        sd="2025-01-01",
        file_format="csv",
        output_path=str(output_path),
        return_data=True,
    )

    assert output_path.exists()
    assert isinstance(result, pd.DataFrame)
    assert result.loc[0, "celex"] == "62025CJ0001"


def test_get_cellar_save_to_output_dir_creates_only_requested_parents(monkeypatch, tmp_path):
    monkeypatch.setattr(cellar, "get_all_eclis", lambda starting_date, ending_date, limit=None: ["E1"])
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: _base_metadata("E1", "62025CJ0001"),
    )
    output_dir = tmp_path / "nested" / "exports"

    cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save=True,
        max_ecli=10,
        sd="2025-01-01",
        file_format="json",
        output_dir=str(output_dir),
    )

    assert output_dir.exists()
    assert any(output_dir.iterdir())
    assert not (tmp_path / "data").exists()


def test_get_cellar_passes_limit_to_ecli_lookup(monkeypatch):
    seen = {}

    def _fake_get_all_eclis(starting_date, ending_date, limit=None):
        seen["limit"] = limit
        return ["E1"]

    monkeypatch.setattr(cellar, "get_all_eclis", _fake_get_all_eclis)
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: _base_metadata("E1", "62025CJ0001"),
    )

    cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save=False,
        max_ecli=1,
        sd="2025-01-01",
        file_format="csv",
    )

    assert seen["limit"] == 1


def test_get_cellar_preserves_ecli_order_across_parallel_metadata_batches(monkeypatch):
    eclis = [f"ECLI:EU:C:2025:{index}" for index in range(105)]
    monkeypatch.setattr(
        cellar,
        "get_all_eclis",
        lambda starting_date, ending_date, limit=None: eclis[:limit] if limit else eclis,
    )

    def _fake_get_raw_cellar_metadata(batch):
        if batch[0] == eclis[0]:
            time.sleep(0.05)
        return {
            ecli: {
                "case-law_ecli": [ecli],
                "resource_legal_id_celex": [f"6{index:09d}"],
                "work_date_document": ["2025-01-01"],
                "resource_legal_type": ["CJ"],
                "resource_legal_id_sector": ["6"],
            }
            for index, ecli in enumerate(batch)
        }

    monkeypatch.setattr(cellar, "get_raw_cellar_metadata", _fake_get_raw_cellar_metadata)

    df = cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save=False,
        max_ecli=105,
        sd="2025-01-01",
        file_format="csv",
    )

    assert df["ecli"].tolist() == eclis


def test_get_cellar_extra_in_memory_calls_extra(monkeypatch):
    base_df = pd.DataFrame({"ecli": ["E1"], "celex": ["62025CJ0001"]})
    monkeypatch.setattr(cellar, "get_cellar", lambda **kwargs: base_df)
    called = {}

    def _fake_extra(data, threads, username, password, metadata_output_path=None, fulltext_output_path=None):
        called["threads"] = threads
        called["username"] = username
        called["password"] = password
        called["metadata_output_path"] = metadata_output_path
        called["fulltext_output_path"] = fulltext_output_path
        return data.copy(), [{"celex": "62025CJ0001", "ecli": "E1", "text": "x"}]

    monkeypatch.setattr(cellar, "extra_cellar", _fake_extra)

    data, fulltext = cellar.get_cellar_extra(
        ed="2025-01-02T00:00:00",
        save=False,
        max_ecli=10,
        sd="2025-01-01",
        threads=4,
        username="user",
        password="pass",
    )

    assert len(data) == 1
    assert len(fulltext) == 1
    assert called == {
        "threads": 4,
        "username": "user",
        "password": "pass",
        "metadata_output_path": None,
        "fulltext_output_path": None,
    }


def test_get_cellar_extra_save_file_calls_extra_with_path(monkeypatch, tmp_path):
    base_df = pd.DataFrame({"ecli": ["E1"], "celex": ["62025CJ0001"]})
    monkeypatch.setattr(cellar, "get_cellar", lambda **kwargs: base_df)
    called = {}

    def _fake_extra(data, threads, username, password, metadata_output_path=None, fulltext_output_path=None):
        called["metadata_output_path"] = metadata_output_path
        called["fulltext_output_path"] = fulltext_output_path
        called["threads"] = threads
        called["username"] = username
        called["password"] = password
        return data, []

    monkeypatch.setattr(cellar, "extra_cellar", _fake_extra)

    cellar.get_cellar_extra(
        ed="2025-01-02T00:00:00",
        save=True,
        max_ecli=10,
        sd="2025-01-01",
        threads=3,
    )

    assert str(called["metadata_output_path"]).replace("\\", "/").endswith(
        "data/cellar_extra_2025-01-01_2025-01-02T00_00_00.csv"
    )
    assert str(called["fulltext_output_path"]).replace("\\", "/").endswith(
        "data/cellar_extra_2025-01-01_2025-01-02T00_00_00_fulltext.json"
    )
    assert called["threads"] == 3


def test_get_cellar_extra_supports_independent_output_paths(monkeypatch, tmp_path):
    base_df = pd.DataFrame({"ecli": ["E1"], "celex": ["62025CJ0001"]})
    monkeypatch.setattr(cellar, "get_cellar", lambda **kwargs: base_df)
    called = {}

    def _fake_extra(data, threads, username, password, metadata_output_path=None, fulltext_output_path=None):
        called["metadata_output_path"] = metadata_output_path
        called["fulltext_output_path"] = fulltext_output_path
        return data, [{"celex": "62025CJ0001"}]

    monkeypatch.setattr(cellar, "extra_cellar", _fake_extra)

    output = cellar.get_cellar_extra(
        ed="2025-01-02T00:00:00",
        save=True,
        max_ecli=10,
        sd="2025-01-01",
        threads=3,
        metadata_output_path=str(tmp_path / "metadata.csv"),
        save_fulltext=False,
        return_data=True,
    )

    assert called["metadata_output_path"] == tmp_path / "metadata.csv"
    assert called["fulltext_output_path"] is None
    assert output[1] == [{"celex": "62025CJ0001"}]


def test_get_cellar_extra_in_memory_does_not_create_default_output_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    base_df = pd.DataFrame({"ecli": ["E1"], "celex": ["62025CJ0001"]})
    monkeypatch.setattr(cellar, "get_cellar", lambda **kwargs: base_df)
    monkeypatch.setattr(
        cellar,
        "extra_cellar",
        lambda **kwargs: (kwargs["data"], [{"celex": "62025CJ0001"}]),
    )

    cellar.get_cellar_extra(
        ed="2025-01-02T00:00:00",
        save=False,
        max_ecli=10,
        sd="2025-01-01",
        threads=1,
    )

    assert not (tmp_path / "data").exists()


def test_get_cellar_save_file_alias_still_works(monkeypatch):
    monkeypatch.setattr(cellar, "get_all_eclis", lambda starting_date, ending_date, limit=None: ["E1"])
    monkeypatch.setattr(
        cellar,
        "get_raw_cellar_metadata",
        lambda eclis: _base_metadata("E1", "62025CJ0001"),
    )

    output = cellar.get_cellar(
        ed="2025-01-02T00:00:00",
        save_file="n",
        max_ecli=10,
        sd="2025-01-01",
        file_format="json",
    )

    assert isinstance(output, dict)


def test_filter_subject_matter_case_insensitive():
    df = pd.DataFrame(
        {
            "subject_matter": [
                "Competition law",
                "Tax law",
                "",
            ]
        }
    )

    filtered = cellar.filter_subject_matter(df=df, phrase="competition")
    assert len(filtered) == 1
