from cellar_extractor import fulltext_saving


def test_fetch_context_uses_confirmed_celex_with_cellar():
    context = fulltext_saving._fetch_context("62016CJ0685", "62016CJ0685", "id_1")

    assert context == {
        "celex": "62016CJ0685",
        "lookup_celex": "62016CJ0685",
        "document_id": "id_1",
        "use_cellar": True,
    }


def test_fetch_context_for_infocuria_only_document_disables_cellar():
    context = fulltext_saving._fetch_context(float("nan"), "62007CO0193", "id_60821")

    assert context == {
        "celex": "",
        "lookup_celex": "62007CO0193",
        "document_id": "id_60821",
        "use_cellar": False,
    }


def test_fetch_context_without_identity_skips_fetch():
    assert fulltext_saving._fetch_context("", "62007CO0193", "")["lookup_celex"] == ""


def test_fetch_context_never_uses_cellar_for_infocuria_identity():
    context = fulltext_saving._fetch_context(
        "62007CO0193", "62007CO0193", "id_60821", identity_source="infocuria"
    )

    assert context == {
        "celex": "62007CO0193",
        "lookup_celex": "62007CO0193",
        "document_id": "id_60821",
        "use_cellar": False,
    }
