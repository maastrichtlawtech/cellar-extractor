import os

import pandas as pd
import pytest

from cellar_extractor import eurlex_scraping
from cellar_extractor.eurlex_scraping import get_case_data_by_celex_id
from cellar_extractor.fulltext_saving import add_sections


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SECTOR8_INTEGRATION") != "1",
    reason="Set RUN_SECTOR8_INTEGRATION=1 to run live sector-8 integration tests.",
)


@pytest.fixture(autouse=True)
def _clear_case_cache():
    eurlex_scraping._get_case_data_cached.cache_clear()
    yield
    eurlex_scraping._get_case_data_cached.cache_clear()


def test_sector8_case_data_live_has_text_and_summary():
    data = get_case_data_by_celex_id("82010AT0127(51)", language="EN")
    assert data is not None
    assert data["sector"] == "8"
    assert len(data["text"]) > 100
    assert len(data["summary"]) > 100
    assert data["text_source"] == "CELLAR_ITEM"
    assert data["summary_source"] == "CELLAR_SUMMARY_ITEM"
    assert data["missing_reasons"] == ""


def test_sector8_case_data_live_flags_unavailable_upstream():
    data = get_case_data_by_celex_id("81994FR0111(01)", language="EN")
    assert data is not None
    assert data["sector"] == "8"
    assert data["text"] == ""
    assert data["summary"] == ""
    assert "UNAVAILABLE_UPSTREAM" in data["missing_reasons"]


def test_mixed_sector_add_sections_live_uses_non_legacy_paths():
    df = pd.DataFrame(
        {
            "CELEX IDENTIFIER": ["62024CJ0131", "82010AT0127(51)"],
            "ECLI": ["ECLI:EU:C:2026:172", "ECLI:AT:OGH0002:2010:0030OB00251.09X.0127.000"],
        }
    )

    add_sections(df, threads=1)

    assert df.loc[0, "fulltext_source"] == "INFOCURIA_BLOB_HTML"
    assert df.loc[1, "fulltext_source"] == "CELLAR_ITEM"
    assert df.loc[1, "summary_source"] == "CELLAR_SUMMARY_ITEM"
    assert df.loc[1, "missing_reasons"] == ""
