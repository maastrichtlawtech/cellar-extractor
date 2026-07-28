import time
from datetime import date, datetime, timedelta

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
