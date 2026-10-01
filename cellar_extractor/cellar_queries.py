import re
import time
from datetime import date, datetime, timedelta

import requests
from SPARQLWrapper import SPARQLWrapper, JSON, POST

# Literal placeholder CELLAR emits while a property is awaiting curation;
# it is noise in every column it lands in (seen on
# case_law_is_about_concept_case_law, among others).
CELLAR_PLACEHOLDER_VALUES = {"Provisional data"}

DEFAULT_ECLI_START_DATE = "1954-01-01"
MAX_SORTED_TOP_LIMIT = 10000
ECLI_WINDOW_DAYS = 366
SPARQL_REQUEST_TIMEOUT_SECONDS = 30
SPARQL_RETRY_BACKOFF_BASE_SECONDS = 0.5
INFOCURIA_SEARCH_ENDPOINT = "https://infocuriaws.curia.europa.eu/elastic-connector/search"
INFOCURIA_PAGE_SIZE = 100
INFOCURIA_REQUEST_TIMEOUT_SECONDS = 60
INFOCURIA_IDENTITY_FIELDS = {
    "case-law_ecli",
    "resource_legal_id_celex",
    "work_date_document",
    "resource_legal_type",
    "resource_legal_id_sector",
    "case-law_affaire_number",
}


def _query_with_retries(sparql, retries, error_message):
    sparql.setTimeout(SPARQL_REQUEST_TIMEOUT_SECONDS)
    last_error = None
    for attempt in range(retries):
        try:
            return sparql.queryAndConvert()
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(SPARQL_RETRY_BACKOFF_BASE_SECONDS * (2**attempt))
    raise RuntimeError(error_message) from last_error


def _coerce_date(value, fallback):
    if value is None:
        value = fallback
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def _build_ecli_query(starting_date=None, ending_date=None, limit=None):
    return """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        select
        distinct ?ecli
        where {
            ?doc cdm:case-law_ecli ?ecli .
            ?doc <%s> ?date .
            %s
            %s
        }
        order by asc(?ecli)
        %s
    """ % (
        "http://publications.europa.eu/ontology/cdm#work_date_document",
        f'FILTER(STR(?date) >= "{starting_date}")' if starting_date else "",
        f'FILTER(STR(?date) <= "{ending_date}")' if ending_date else "",
        f"LIMIT {limit}" if limit else "",
    )


def _extract_eclis(ret):
    eclis = []
    for res in ret["results"]["bindings"]:
        eclis.append(res["ecli"]["value"])
    return eclis


def _query_ecli_window(starting_date=None, ending_date=None, limit=None, max_retries=3):
    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(JSON)
    sparql.setQuery(
        _build_ecli_query(
            starting_date=starting_date, ending_date=ending_date, limit=limit
        )
    )
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to query CELLAR ECLI list after retries",
    )
    return _extract_eclis(ret)


def _build_ecli_windows(starting_date=None, ending_date=None, window_days=None):
    if window_days is None:
        window_days = ECLI_WINDOW_DAYS
    start_raw = starting_date or DEFAULT_ECLI_START_DATE
    end_raw = ending_date or datetime.now().date().isoformat()

    start_date = _coerce_date(start_raw, DEFAULT_ECLI_START_DATE)
    end_date = _coerce_date(end_raw, datetime.now().date().isoformat())
    if start_date > end_date:
        raise ValueError("starting_date must be earlier than or equal to ending_date")

    windows = []
    current = start_date
    while current <= end_date:
        current_end = min(current + timedelta(days=window_days - 1), end_date)
        window_start = start_raw if current == start_date else current.isoformat()
        window_end = end_raw if current_end == end_date else current_end.isoformat()
        windows.append((window_start, window_end))
        current = current_end + timedelta(days=1)
    return windows


def get_all_eclis(starting_date=None, ending_date=None, limit=None, max_retries=3):
    """Gets a list of all ECLIs in CELLAR. If this needs to be picked up
    from a previous run,
    the last ECLI parsed in that run can be used as starting point for this run

    :param starting_date: Document modification date to start off from.
        Can be set to last run to only get updated documents.
        Ex. 2020-03-19T09:41:10.351+01:00
    :type starting_date: str, optional
    :param ending_date: Document modification date to end at.
    :type ending_date : str,optional
    :param limit: Maximum number of ECLIs to return from the endpoint.
    :type limit: int, optional
    :return:  A list of all (filtered) ECLIs in CELLAR.
    :rtype: list[str]
    """

    # Small requests can safely stay as a single endpoint-side sorted query.
    if limit and limit <= MAX_SORTED_TOP_LIMIT:
        return _query_ecli_window(
            starting_date=starting_date,
            ending_date=ending_date,
            limit=limit,
            max_retries=max_retries,
        )

    collected = set()
    for window_start, window_end in _build_ecli_windows(
        starting_date=starting_date, ending_date=ending_date
    ):
        remaining = None if limit is None else limit - len(collected)
        if remaining is not None and remaining <= 0:
            break

        window_limit = (
            remaining if remaining and remaining <= MAX_SORTED_TOP_LIMIT else None
        )
        collected.update(
            _query_ecli_window(
                starting_date=window_start,
                ending_date=window_end,
                limit=window_limit,
                max_retries=max_retries,
            )
        )

    eclis = sorted(collected)
    if limit is not None:
        return eclis[:limit]
    return eclis


CELEX_PATTERN = re.compile(r"^6\d{4}[A-Z]{1,2}\d{4}(?:\(\d{2}\))?$")


def _infocuria_celex_tokens(value):
    """Return the distinct canonical CELEX values listed in an InfoCuria hit.

    InfoCuria writes numbered document variants as ``.01`` while EUR-Lex and
    CELLAR use ``(01)``, and some hits list several CELEX values separated by
    whitespace or ``;``. Derived summary/information works are dropped
    instead of being collapsed onto their base CELEX.
    """
    if value is None:
        return []
    tokens = []
    for raw in re.split(r"[\s;,]+", str(value).strip()):
        if raw == "" or re.search(r"_(?:SUM|RES|INF)$", raw, flags=re.IGNORECASE):
            continue
        celex = re.sub(r"\.(\d{2})$", r"(\1)", raw)
        if CELEX_PATTERN.match(celex) and celex not in tokens:
            tokens.append(celex)
    return tokens


def _normalize_infocuria_celex(value):
    """Return the hit's CELEX when it names exactly one primary document."""
    tokens = _infocuria_celex_tokens(value)
    return tokens[0] if len(tokens) == 1 else ""


def _build_infocuria_search_payload(starting_date, ending_date, page_number, page_size):
    start = page_number * page_size + 1
    return {
        "multiSearchTerms": [],
        "searchTerm": "",
        "ecli": "",
        "publishedId": "",
        "usualName": "",
        "logicDocId": "",
        "repJurExpand": False,
        "pagination": {
            "pageNumber": page_number,
            "pageSize": page_size,
            "from": start,
            "to": start + page_size - 1,
            "origin": "jurisprudence",
        },
        "sortTermList": [
            {
                "sortDirection": "ASC",
                "sortTerm": "DOC_DATE",
                "sortSourceTab": "jurisprudence",
            }
        ],
        "filtersValue": [{"field": "docDate", "values": [starting_date, ending_date]}],
        "advancedFiltersValue": [],
        "language": "EN",
        "isSearchExact": False,
        "searchSources": ["document", "metadata"],
        "tabName": "jurisprudence",
        "isAllTabsRequest": False,
    }


def _query_infocuria_page(payload, max_retries):
    last_error = None
    for attempt in range(max_retries):
        try:
            response = requests.post(
                INFOCURIA_SEARCH_ENDPOINT,
                json=payload,
                timeout=INFOCURIA_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("InfoCuria search response is not an object")
            return result
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(SPARQL_RETRY_BACKOFF_BASE_SECONDS * (2**attempt))
    raise RuntimeError(
        "Failed to query InfoCuria document catalogue after retries"
    ) from last_error


def _infocuria_metadata_from_hit(hit):
    content = hit.get("content", {}) if isinstance(hit, dict) else {}
    if not isinstance(content, dict):
        return None

    ecli = str(content.get("ecli") or "").strip()
    tokens = _infocuria_celex_tokens(content.get("celex"))
    document_date = str(content.get("docDate") or "").strip()
    if not ecli.startswith("ECLI:EU:") or not tokens or document_date == "":
        return None

    celex = tokens[0] if len(tokens) == 1 else ""
    metadata = {
        "case-law_ecli": [ecli],
        "work_date_document": [document_date],
        "resource_legal_id_sector": ["6"],
        "metadata_catalog_source": ["infocuria"],
        # InfoCuria's CELEX is often the procedure's, shared by every order
        # in a case, so it is kept separately from the document identity.
        "infocuria_celex": [";".join(tokens)],
    }
    if celex:
        metadata["resource_legal_id_celex"] = [celex]
        metadata["resource_legal_type"] = [celex[5:7]]
    for field, key in (
        ("infocuria_document_id", "logicDocId"),
        ("infocuria_procedure_id", "idProcedure"),
        ("infocuria_document_type", "docType"),
        ("case-law_affaire_number", "idPublished"),
    ):
        value = str(content.get(key) or "").strip()
        if value:
            metadata[field] = [value]
    return ecli, metadata


def _is_information_notice(metadata):
    document_type = (metadata.get("infocuria_document_type") or [""])[0]
    return "information" in document_type.lower()


def get_infocuria_document_metadata(
    starting_date=None,
    ending_date=None,
    limit=None,
    max_retries=3,
):
    """Enumerate official InfoCuria documents for a date range.

    CELLAR's SPARQL graph does not contain every document that is available
    through EUR-Lex/InfoCuria, particularly procedural orders. InfoCuria is
    therefore used as a second catalogue source. Results use the same
    predicate-map shape as :func:`get_raw_cellar_metadata` so callers can
    reconcile the sources before normal schema flattening.
    """
    metadata = {}
    for window_start, window_end in _build_ecli_windows(
        starting_date=starting_date,
        ending_date=ending_date,
    ):
        page_number = 0
        while True:
            remaining = None if limit is None else limit - len(metadata)
            if remaining is not None and remaining <= 0:
                return metadata
            page_size = INFOCURIA_PAGE_SIZE

            payload = _build_infocuria_search_payload(
                str(window_start)[:10],
                str(window_end)[:10],
                page_number,
                page_size,
            )
            result = _query_infocuria_page(payload, max_retries=max_retries)
            hits = result.get("searchHits", [])
            if not isinstance(hits, list):
                raise RuntimeError("InfoCuria catalogue returned invalid searchHits")

            for hit in hits:
                parsed = _infocuria_metadata_from_hit(hit)
                if parsed is None:
                    continue
                ecli, values = parsed
                # Multiple logical documents can share an ECLI, typically a
                # decision and its "(Information)" notice. Keep the decision;
                # otherwise the first hit, which is deterministic because the
                # endpoint is date-sorted.
                if ecli not in metadata or (
                    _is_information_notice(metadata[ecli])
                    and not _is_information_notice(values)
                ):
                    metadata[ecli] = values
                if limit is not None and len(metadata) >= limit:
                    return metadata

            total_hits = int(result.get("totalHits") or 0)
            consumed = (page_number + 1) * page_size
            if not hits or consumed >= total_hits:
                break
            page_number += 1
    return metadata


INFOCURIA_LOCATOR_FIELDS = (
    "metadata_catalog_source",
    "infocuria_celex",
    "infocuria_document_id",
    "infocuria_procedure_id",
    "infocuria_document_type",
)


def _first_celex(values_by_key):
    values = values_by_key.get("resource_legal_id_celex") or []
    for value in values:
        celex = str(value).split(";", 1)[0].split("_", 1)[0].strip()
        if celex:
            return celex
    return ""


def reconcile_document_metadata(
    cellar_metadata, infocuria_metadata, celex_owners=None
):
    """Merge both catalogues without letting InfoCuria rewrite CELLAR identity.

    CELEX is EUR-Lex's identifier and CELLAR is its store, so an ECLI CELLAR
    knows keeps CELLAR's identity; InfoCuria only adds its document locator
    and fills empty fields. InfoCuria's CELEX is often the procedure's rather
    than the document's (every order in a case shares it), so documents known
    only to InfoCuria keep it only when it is unambiguous: not claimed by
    another ECLI in CELLAR (``celex_owners(celex) -> set of ECLIs``) and not
    shared with another document in this batch. Otherwise the document keeps
    no CELEX, and callers fetch its text through ``infocuria_document_id``.
    """
    reconciled = {
        ecli: {key: list(values) for key, values in values_by_key.items()}
        for ecli, values_by_key in (cellar_metadata or {}).items()
    }
    for ecli in reconciled:
        reconciled[ecli]["identity_source"] = ["cellar"]

    infocuria_only = {}
    for ecli, values_by_key in (infocuria_metadata or {}).items():
        if ecli in reconciled:
            target = reconciled[ecli]
            for key, values in values_by_key.items():
                if key in INFOCURIA_LOCATOR_FIELDS or (
                    key not in INFOCURIA_IDENTITY_FIELDS and not target.get(key)
                ):
                    target[key] = list(values)
            continue
        record = {key: list(values) for key, values in values_by_key.items()}
        record["identity_source"] = ["infocuria"]
        infocuria_only[ecli] = record

    celex_users = {}
    for ecli, record in list(reconciled.items()) + list(infocuria_only.items()):
        celex = _first_celex(record)
        if celex:
            celex_users.setdefault(celex, set()).add(ecli)

    for ecli, record in infocuria_only.items():
        celex = _first_celex(record)
        if celex:
            claimed = celex_users[celex] - {ecli}
            if not claimed and celex_owners is not None:
                claimed = set(celex_owners(celex)) - {ecli}
            if claimed:
                record.pop("resource_legal_id_celex", None)
                record.pop("resource_legal_type", None)
        reconciled[ecli] = record
    return reconciled


def get_cellar_celex_owners(celex, max_retries=3):
    """Return the ECLIs CELLAR binds to works carrying ``celex``."""
    escaped = celex.replace("\\", "\\\\").replace('"', '\\"')
    query = f"""
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        select distinct ?ecli
        where {{
            ?doc cdm:resource_legal_id_celex ?celex .
            FILTER(STR(?celex) = "{escaped}")
            ?doc cdm:case-law_ecli ?ecli .
        }}
    """
    sparql = SPARQLWrapper("https://publications.europa.eu/webapi/rdf/sparql")
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)
    sparql.setTimeout(SPARQL_REQUEST_TIMEOUT_SECONDS)
    sparql.setQuery(query)
    result = _query_with_retries(
        sparql, max_retries, f"Failed to resolve CELLAR owners of {celex}"
    )
    return {
        row["ecli"]["value"]
        for row in result.get("results", {}).get("bindings", [])
        if row.get("ecli", {}).get("value")
    }


def get_raw_cellar_metadata_by_celex(
    celex_ids,
    get_labels=True,
    force_readable_cols=True,
    force_readable_vals=False,
    max_retries=3,
):
    """Fetch CELLAR metadata triples keyed by CELEX rather than by ECLI.

    Same shape as get_raw_cellar_metadata. Property keys are CDM predicate URI
    local parts (stable IDs); values use skos:prefLabel resolution when
    available, falling back to the raw object value. The legacy
    get_labels / force_readable_* parameters are retained for backwards
    compatibility but are now no-ops.
    """
    del get_labels, force_readable_cols, force_readable_vals  # legacy no-ops
    if not celex_ids:
        return {}

    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    escaped = '", "'.join(celex_ids)
    query = (
        """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        prefix skos: <http://www.w3.org/2004/02/skos/core#>
        select
        distinct ?celex ?p ?o ?olabel
        where {
            ?doc cdm:resource_legal_id_celex ?celex .
            FILTER(STR(?celex) in ("%s"))
            ?doc ?p ?o .
            OPTIONAL {
                ?o skos:prefLabel ?olabel .
                FILTER(lang(?olabel) = "en") .
            }
        }
    """
        % escaped
    )

    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to query CELLAR metadata by CELEX after retries",
    )

    metadata = {celex: {} for celex in celex_ids}
    for res in ret["results"]["bindings"]:
        celex = res["celex"]["value"]
        if celex not in metadata:
            metadata[celex] = {}
        predicate_uri = res["p"]["value"]
        if not predicate_uri.startswith("http://publications.europa.eu/ontology/cdm"):
            continue
        key = predicate_uri.rsplit("#", 1)[-1]
        val = res.get("olabel", {}).get("value") or res["o"]["value"]
        if val in CELLAR_PLACEHOLDER_VALUES:
            continue
        metadata[celex].setdefault(key, []).append(val)
    return metadata


def get_raw_cellar_metadata(
    eclis,
    get_labels=True,
    force_readable_cols=True,
    force_readable_vals=False,
    max_retries=3,
):
    """Fetch CDM predicate triples for each ECLI.

    Returns a dict ``{ecli: {predicate_local_part: [values, ...]}}``. Property
    keys are stable CDM predicate URI local parts (e.g. ``case-law_ecli``,
    ``resource_legal_id_celex``); values use skos:prefLabel resolution when
    available, falling back to the raw object value. The legacy
    get_labels / force_readable_* parameters are retained for backwards
    compatibility but are now no-ops.
    """
    del get_labels, force_readable_cols, force_readable_vals  # legacy no-ops
    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    query = """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        prefix skos: <http://www.w3.org/2004/02/skos/core#>
        select
        distinct ?ecli ?p ?o ?olabel
        where {
            ?doc cdm:case-law_ecli ?ecli .
            FILTER(STR(?ecli) in ("%s"))
            ?doc ?p ?o .
            OPTIONAL {
                ?o skos:prefLabel ?olabel .
                FILTER(lang(?olabel) = "en") .
            }
        }
    """ % '", "'.join(
        eclis
    )

    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to query CELLAR metadata after retries",
    )

    metadata = {ecli: {} for ecli in eclis}
    for res in ret["results"]["bindings"]:
        ecli = res["ecli"]["value"]
        predicate_uri = res["p"]["value"]
        if not predicate_uri.startswith("http://publications.europa.eu/ontology/cdm"):
            continue
        key = predicate_uri.rsplit("#", 1)[-1]
        val = res.get("olabel", {}).get("value") or res["o"]["value"]
        if val in CELLAR_PLACEHOLDER_VALUES:
            continue
        metadata[ecli].setdefault(key, []).append(val)
    return metadata
