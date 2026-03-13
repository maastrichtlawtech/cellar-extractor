import json
from pathlib import Path

from cellar_extractor.operative_extractions import FetchOperativePart, Writing


class _FakeSparql:
    def __init__(self, payload):
        self.payload = payload
        self.query = ""

    def setReturnFormat(self, _fmt):
        return None

    def setQuery(self, query):
        self.query = query

    def queryAndConvert(self):
        return self.payload


def test_get_operative_sparql_query_includes_owl_prefix():
    payload = {"results": {"bindings": []}}
    fetcher = FetchOperativePart("61986CJ0062")
    fake = _FakeSparql(payload)
    fetcher.sparql = fake

    fetcher.get_operative_sparql()

    assert "PREFIX owl:" in fake.query


def test_get_operative_sparql_parses_html():
    payload = {
        "results": {
            "bindings": [{"operative": {"value": "<p>Operative text</p>"}}],
        }
    }
    fetcher = FetchOperativePart("61986CJ0062")
    fetcher.sparql = _FakeSparql(payload)

    result = fetcher.get_operative_sparql()

    assert result == "Operative text"


def test_writing_uses_explicit_output_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(FetchOperativePart, "__call__", lambda self: ["First", "Second"])
    writer = Writing("61986CJ0062")

    csv_path = tmp_path / "custom" / "operative.csv"
    json_path = tmp_path / "custom" / "operative.json"
    txt_path = tmp_path / "custom" / "operative.txt"

    writer.to_csv(str(csv_path))
    writer.to_json(str(json_path))
    writer.to_txt(str(txt_path))

    assert csv_path.exists()
    assert "61986CJ0062" in csv_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload[0]["Celex"] == "61986CJ0062"
    assert txt_path.read_text(encoding="utf-8") == "First\nSecond\n"


def test_writing_init_has_no_filesystem_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(FetchOperativePart, "__call__", lambda self: ["Only"])

    Writing("61986CJ0062")

    assert list(tmp_path.iterdir()) == []


def test_to_json_appends_to_existing_json_list(tmp_path, monkeypatch):
    monkeypatch.setattr(FetchOperativePart, "__call__", lambda self: ["Only"])
    output_path = tmp_path / "operative.json"
    output_path.write_text(json.dumps([{"Celex": "OLD", "Operative part": ["Prev"]}]), encoding="utf-8")

    Writing("61986CJ0062").to_json(str(output_path))

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["Celex"] for item in payload] == ["OLD", "61986CJ0062"]
