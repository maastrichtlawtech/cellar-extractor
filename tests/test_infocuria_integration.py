import os

import pytest

from cellar_extractor import eurlex_scraping
from cellar_extractor.eurlex_scraping import (
    get_case_data_by_celex_id,
    get_entire_page,
    get_html_text_by_celex_id,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INFOCURIA_INTEGRATION") != "1",
    reason="Set RUN_INFOCURIA_INTEGRATION=1 to run live InfoCuria integration tests.",
)


@pytest.fixture(autouse=True)
def _clear_infocuria_cache():
    eurlex_scraping._get_case_data_cached.cache_clear()
    yield
    eurlex_scraping._get_case_data_cached.cache_clear()


def test_infocuria_case_data_live():
    data = get_case_data_by_celex_id("62024CJ0131", language="EN")
    assert data is not None
    assert len(data["html"]) > 1000
    assert len(data["summary"]) > 100
    assert data["directory_codes"] != ""


def test_infocuria_html_wrapper_live():
    html = get_html_text_by_celex_id("62024CJ0131")
    assert html != "404"
    assert len(html) > 1000


def test_infocuria_entire_page_wrapper_live():
    page = get_entire_page("62024CJ0131")
    assert page != "No data available"
    assert "Case law directory code:" in page
