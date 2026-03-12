import os
import time
from pathlib import Path

import xmltodict
import pandas as pd
import pytest

from cellar_extractor.citations_adder import (
    add_citations_separate,
    add_citations_separate_webservice,
)
from cellar_extractor.eurlex_scraping import extract_dictionary_from_webservice_query
from cellar_extractor.sparql import run_eurlex_webservice_query

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_WEBSERVICE_INTEGRATION") != "1",
    reason="Set RUN_WEBSERVICE_INTEGRATION=1 to run legacy EUR-Lex webservice tests.",
)


def _read_env_file():
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    values = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def _get_credential(name, env_values):
    return os.getenv(name) or env_values.get(name, "")


@pytest.fixture(scope="module")
def webservice_ready():
    env_values = _read_env_file()
    username = _get_credential("EURLEX_WEBSERVICE_USERNAME", env_values)
    password = _get_credential("EURLEX_WEBSERVICE_PASSWORD", env_values)
    if not username or not password:
        pytest.skip(
            "No EUR-Lex webservice credentials found. "
            "Set EURLEX_WEBSERVICE_USERNAME and EURLEX_WEBSERVICE_PASSWORD in .env."
        )

    _run_legacy_query_or_skip(" SELECT CI, DN WHERE DN = 62019CJ0668", username, password)

    return username, password


def _normalize_relation(value):
    if pd.isna(value) or value == "":
        return set()
    return {part.strip() for part in str(value).split(";") if part.strip()}


def _extract_notice_work_keys(response):
    read = xmltodict.parse(response.text)
    results = read["S:Envelope"]["S:Body"]["searchResults"]["result"]
    if isinstance(results, list):
        work = results[0]["content"]["NOTICE"]["WORK"]
    else:
        work = results["content"]["NOTICE"]["WORK"]
    return set(work.keys())


def _fault_reason(response):
    try:
        read = xmltodict.parse(response.text)
        fault = read["env:Envelope"]["env:Body"]["env:Fault"]
        code = fault["Code"]["Subcode"]["Value"]
        reason = fault["Reason"]["Text"]["#text"]
        return f"{code}: {reason}"
    except Exception:
        text = str(response.text).replace("\n", " ").strip()
        return text[:240]


def _run_legacy_query_or_skip(query, username, password, retries=3, delay=1.0):
    last_response = None
    for _ in range(retries):
        response = run_eurlex_webservice_query(query, username, password)
        last_response = response
        if response.status_code == 200:
            return response
        if response.status_code == 403:
            pytest.skip("EUR-Lex webservice returned 403 during legacy redundancy test.")
        if response.status_code == 500 and "WS_MAXIMUM_NB_OF_WS_CALLS" in response.text:
            pytest.skip("EUR-Lex webservice daily call limit reached during legacy redundancy test.")
        time.sleep(delay)

    pytest.skip(
        "EUR-Lex webservice was unstable during legacy redundancy validation. "
        f"Last response: {_fault_reason(last_response)}"
    )


def test_webservice_current_pipeline_data_is_citation_only(webservice_ready):
    username, password = webservice_ready
    response = _run_legacy_query_or_skip(
        " SELECT CI, DN WHERE DN = 62019CJ0668", username, password
    )

    assert response.status_code == 200
    work_keys = _extract_notice_work_keys(response)
    assert "ID_CELEX" in work_keys
    assert "WORK_CITES_WORK" in work_keys
    assert "WORK_DATE_DOCUMENT" in work_keys


def test_webservice_outbound_citations_match_sparql_for_sample_cases(webservice_ready):
    username, password = webservice_ready
    sample = ["62019CJ0668", "62019CJ0667", "62024CJ0131"]
    sparql_df = pd.DataFrame({"CELEX IDENTIFIER": sample})
    add_citations_separate(sparql_df, threads=1)

    for idx, celex in enumerate(sample):
        response = _run_legacy_query_or_skip(
            f" SELECT CI, DN WHERE DN = {celex}", username, password
        )
        soap_dict = extract_dictionary_from_webservice_query(response)
        assert _normalize_relation(soap_dict.get(celex, "")) == _normalize_relation(
            sparql_df.loc[idx, "citing"]
        )


def test_webservice_does_not_cover_inbound_citations_like_sparql(webservice_ready):
    username, password = webservice_ready
    sample = pd.DataFrame({"CELEX IDENTIFIER": ["62019CJ0668", "62019CJ0667"]})

    soap_df = sample.copy()
    sparql_df = sample.copy()

    with pytest.warns(DeprecationWarning, match="deprecated"):
        add_citations_separate_webservice(soap_df, username, password)
    add_citations_separate(sparql_df, threads=1)

    for idx in range(len(sample)):
        assert _normalize_relation(soap_df.loc[idx, "cited_by"]) == set()
        assert len(_normalize_relation(sparql_df.loc[idx, "cited_by"])) > 0
