import os
from pathlib import Path

import pytest
import xmltodict

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


def _fault_excerpt(response, limit=240):
    text = str(response.text).replace("\n", " ").strip()
    return text[:limit]


def _fault_reason(response):
    try:
        read = xmltodict.parse(response.text)
        fault = read["env:Envelope"]["env:Body"]["env:Fault"]
        code = fault["Code"]["Subcode"]["Value"]
        reason = fault["Reason"]["Text"]["#text"]
        return f"{code}: {reason}"
    except Exception:
        return _fault_excerpt(response)


@pytest.fixture(scope="module")
def webservice_credentials():
    env_values = _read_env_file()
    username = _get_credential("EURLEX_WEBSERVICE_USERNAME", env_values)
    password = _get_credential("EURLEX_WEBSERVICE_PASSWORD", env_values)
    if not username or not password:
        pytest.skip(
            "No EUR-Lex webservice credentials found. "
            "Set EURLEX_WEBSERVICE_USERNAME and EURLEX_WEBSERVICE_PASSWORD in .env."
        )
    return username, password


@pytest.fixture(scope="module")
def webservice_ready(webservice_credentials):
    username, password = webservice_credentials
    probe_query = " SELECT CI, DN WHERE DN = 62019CJ0668"
    response = run_eurlex_webservice_query(probe_query, username, password)

    if response.status_code == 403:
        pytest.skip("EUR-Lex webservice returned 403 (maintenance/block).")
    if response.status_code == 500 and "WS_MAXIMUM_NB_OF_WS_CALLS" in response.text:
        pytest.skip("EUR-Lex webservice daily call limit reached for these credentials.")
    if response.status_code == 500:
        pytest.fail(
            "EUR-Lex webservice returned 500 without the call-limit marker. "
            "Credentials are likely invalid for webservice access. "
            f"SOAP fault: {_fault_reason(response)}"
        )

    return username, password


def test_webservice_credentials_authenticate(webservice_ready):
    username, password = webservice_ready
    response = run_eurlex_webservice_query(
        " SELECT CI, DN WHERE DN = 62019CJ0668", username, password
    )
    assert response.status_code == 200
    assert "<searchResults" in response.text


def test_webservice_query_returns_notice_payload(webservice_ready):
    username, password = webservice_ready
    response = run_eurlex_webservice_query(
        " SELECT CI, DN WHERE DN = 62019CJ0668", username, password
    )
    parsed = xmltodict.parse(response.text)
    results = parsed["S:Envelope"]["S:Body"]["searchResults"]["result"]

    if isinstance(results, list):
        work = results[0]["content"]["NOTICE"]["WORK"]
    else:
        work = results["content"]["NOTICE"]["WORK"]

    assert "ID_CELEX" in work
    assert "WORK_CITES_WORK" in work
