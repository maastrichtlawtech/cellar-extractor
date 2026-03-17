from datetime import date, datetime, timedelta

from SPARQLWrapper import SPARQLWrapper, JSON, POST

DEFAULT_ECLI_START_DATE = "1954-01-01"
MAX_SORTED_TOP_LIMIT = 10000
ECLI_WINDOW_DAYS = 366


def _query_with_retries(sparql, retries, error_message):
    last_error = None
    for _ in range(retries):
        try:
            return sparql.queryAndConvert()
        except Exception as exc:
            last_error = exc
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


def get_raw_cellar_metadata(
    eclis,
    get_labels=True,
    force_readable_cols=True,
    force_readable_vals=False,
    max_retries=3,
):
    """Gets cellar metadata

    :param eclis: The ECLIs for which to retrieve metadata
    :type eclis: list[str]
    :param get_labels: Flag to get human-readable labels for the properties,
    defaults to True
    :type get_labels: bool, optional
    :param force_readable_cols: Flag to remove any non-labelled properties
    from the resulting dict, defaults to True
    :type force_readable_cols: bool, optional
    :param force_readable_vals: Flag to remove any non-labelled values from
    the resulting dict, defaults to False
    :type force_readable_vals: bool, optional
    :return: Dictionary containing metadata. Top-level keys are ECLIs, second
    level are property names
    :rtype: Dict[str, Dict[str, list[str]]]
    """

    # Find every outgoing edge from an ECLI document and return it
    # (essentially giving s -p> o)
    # Also get labels for p/o (optionally) and then make sure to only return
    # distinct triples
    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    query = """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        prefix skos: <http://www.w3.org/2004/02/skos/core#>
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        select
        distinct ?ecli ?p ?o ?plabel ?olabel
        where {
            ?doc cdm:case-law_ecli ?ecli .
            FILTER(STR(?ecli) in ("%s"))
            ?doc ?p ?o .
            OPTIONAL {
                ?p rdfs:label ?plabel
            }
            OPTIONAL {
                ?o skos:prefLabel ?olabel .
                FILTER(lang(?olabel) = "en") .
            }
        }
    """ % (
        '", "'.join(eclis)
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
    # Create one dict for each document
    metadata = {}
    for ecli in eclis:
        metadata[ecli] = {}

    # Take each triple, check which source doc it belongs to, key/value pair
    # into its dict derived from the p and o in the query
    for res in ret["results"]["bindings"]:
        ecli = res["ecli"]["value"]
        # We only want cdm predicates
        if not res["p"]["value"].startswith("http://publications.europa.eu/ontology/cdm"):
            continue

        # Check if we have predicate labels
        if "plabel" in res and get_labels:
            key = res["plabel"]["value"]
        elif force_readable_cols:
            continue
        else:
            key = res["p"]["value"]
            key = key.split("#")[1]

        # Check if we have target labels
        if "olabel" in res and get_labels:
            val = res["olabel"]["value"]
        elif force_readable_vals:
            continue
        else:
            val = res["o"]["value"]

        # We store the values for each property in a list. For some properties
        # this is not necessary, but if a property can be assigned multiple
        # times, this is important. Notable, for example is citations.
        if key in metadata[ecli]:
            metadata[ecli][key].append(val)
        else:
            metadata[ecli][key] = [val]

    return metadata
