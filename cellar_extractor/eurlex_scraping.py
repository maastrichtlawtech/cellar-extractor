import io
import random
import time
import re
import threading
from functools import lru_cache
import requests
import xmltodict
from SPARQLWrapper import JSON, POST, SPARQLWrapper
from requests.adapters import HTTPAdapter

from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - handled in runtime fallback
    PdfReader = None

INFOCURIA_BASE = "https://infocuriaws.curia.europa.eu"
INFOCURIA_SUGGEST = INFOCURIA_BASE + "/elastic-connector/suggest"
INFOCURIA_PROCEDURES = INFOCURIA_BASE + "/elastic-connector/affairId/procedures"
INFOCURIA_BLOB_HTML = (
    INFOCURIA_BASE
    + "/blob/download-file-html/{jurisdiction}/{year}/{process}/{file_name}"
)
CELLAR_SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR_REST_BASE = "https://publications.europa.eu/resource/celex"
HTTP_POOL_SIZE = 8
INFOCURIA_MIN_INTERVAL_SECONDS = 0.05

LANG_AUTH_TO_SHORT = {
    "BUL": "BG",
    "CES": "CS",
    "DAN": "DA",
    "DEU": "DE",
    "ELL": "EL",
    "ENG": "EN",
    "SPA": "ES",
    "EST": "ET",
    "FIN": "FI",
    "FRA": "FR",
    "GLE": "GA",
    "HRV": "HR",
    "HUN": "HU",
    "ITA": "IT",
    "LIT": "LT",
    "LAV": "LV",
    "MLT": "MT",
    "NLD": "NL",
    "POL": "PL",
    "POR": "PT",
    "RON": "RO",
    "SLK": "SK",
    "SLV": "SL",
    "SWE": "SV",
}
LANG_SHORT_TO_AUTH = {v: k for k, v in LANG_AUTH_TO_SHORT.items()}

SECTOR8_MAIN_FORMAT_ORDER = {
    "xhtml": 0,
    "html": 1,
    "xml": 2,
    "pdf": 3,
    "pdfa2a": 3,
}
SECTOR8_SUMMARY_FORMAT_ORDER = {
    "xhtml": 0,
    "html": 1,
    "pdf": 2,
    "pdfa2a": 2,
    "xml": 3,
}

LINK_SUMMARY_INF = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:cIdHere&from=EN"
)
LINK_SUMJURE = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:cIdHere_SUM&from=EN"
)
CELEX_SUBSTITUTE = "cIdHere"
LINK_SUMMARY = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:cIdHere_SUM&from=EN"
)
prog = re.compile(r"^[1234567890CE]\d{4}[A-Z]{1,2}\d{3,4}\d*")
celex_case_pattern = re.compile(r"^6(?P<year>\d{4})(?P<kind>[A-Z]{1,2})(?P<num>\d{1,4})")
"""
Method for detecting code-words for case law directory codes for cellar.
"""

_thread_local = threading.local()
# Per-bucket locks let independent endpoints (InfoCuria suggest, blob-html,
# CELLAR REST, etc.) pace in parallel rather than serialising on a single
# global mutex. The guard lock only protects the registry, never the sleep.
_bucket_locks_guard = threading.Lock()
_bucket_locks = {}
_last_request_at = {}


def _bucket_lock(bucket):
    """Return the lock dedicated to ``bucket``, creating it on first use."""
    with _bucket_locks_guard:
        lock = _bucket_locks.get(bucket)
        if lock is None:
            lock = threading.Lock()
            _bucket_locks[bucket] = lock
        return lock


def _normalize_celex(celex):
    if celex != celex:
        return ""
    value = str(celex).replace(" ", "")
    if ";" in value:
        options = [part.strip() for part in value.split(";") if part.strip()]
        non_inf = [part for part in options if "INF" not in part]
        value = non_inf[0] if non_inf else options[0]
    if "_" in value:
        value = value.split("_")[0]
    return value


def _sleep_with_backoff(attempt, base=0.2):
    time.sleep(base * (attempt + 1) + random.uniform(0.0, 0.1))


def _pace_requests(bucket, min_interval):
    """Throttle requests to ``bucket`` so consecutive calls are at least
    ``min_interval`` apart, **without serialising across buckets** and
    **without holding any lock while sleeping**.

    The bucket's slot is reserved atomically inside the lock (so concurrent
    same-bucket waiters queue up correctly), then the sleep happens with no
    lock held — letting other threads on other buckets proceed in parallel.
    """
    lock = _bucket_lock(bucket)
    with lock:
        now = time.monotonic()
        last = _last_request_at.get(bucket, 0.0)
        wait = min_interval - (now - last)
        # Reserve the next slot atomically. If the previous slot is in the
        # future (because a concurrent waiter already reserved it), our wait
        # extends to one min_interval past that.
        next_slot = max(now, last + min_interval)
        _last_request_at[bucket] = next_slot
    if wait > 0:
        time.sleep(wait)


def _get_http_session():
    session = getattr(_thread_local, "http_session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=HTTP_POOL_SIZE, pool_maxsize=HTTP_POOL_SIZE
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.http_session = session
    return session


def _published_id_from_celex(celex):
    match = celex_case_pattern.match(celex)
    if not match:
        return ""
    year4 = match.group("year")
    kind = match.group("kind")
    number = int(match.group("num"))
    court = kind[0] if kind and kind[0] in {"C", "T", "F"} else ""
    if court == "":
        return ""
    return f"{court}-{number}/{year4[2:]}"


def _post_json(url, payload, retries=3):
    last_error = None
    session = _get_http_session()
    for attempt in range(retries):
        try:
            _pace_requests("infocuria_post", INFOCURIA_MIN_INTERVAL_SECONDS)
            response = session.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:
            last_error = exc
        _sleep_with_backoff(attempt)
    if last_error:
        raise RuntimeError(f"POST request failed for {url}") from last_error
    return None


SPARQL_REQUEST_TIMEOUT_SECONDS = 30


def _query_cellar_sparql(query, retries=3):
    last_error = None
    for attempt in range(retries):
        try:
            sparql = SPARQLWrapper(CELLAR_SPARQL_ENDPOINT)
            sparql.setReturnFormat(JSON)
            sparql.setMethod(POST)
            sparql.setTimeout(SPARQL_REQUEST_TIMEOUT_SECONDS)
            sparql.setQuery(query)
            return sparql.queryAndConvert()
        except Exception as exc:
            last_error = exc
            _sleep_with_backoff(attempt)
    if last_error:
        raise RuntimeError("SPARQL query failed for CELLAR endpoint") from last_error
    return None


def _escape_sparql_literal(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _authority_lang_to_short(authority_lang):
    if authority_lang == "":
        return ""
    clean = authority_lang.upper()
    return LANG_AUTH_TO_SHORT.get(clean, clean[:2])


def _short_lang_to_authority(language):
    if language == "":
        return ""
    clean = language.upper()
    if len(clean) == 3:
        return clean
    return LANG_SHORT_TO_AUTH.get(clean, clean)


def _extract_short_lang_from_uri(uri):
    if not isinstance(uri, str) or uri == "":
        return ""
    authority = uri.rsplit("/", 1)[-1].upper()
    return _authority_lang_to_short(authority)


def _build_missing_reasons(text="", summary=""):
    reasons = []
    if text == "":
        reasons.append("FULLTEXT_UNAVAILABLE_UPSTREAM")
    if summary == "":
        reasons.append("SUMMARY_UNAVAILABLE_UPSTREAM")
    if text == "" and summary == "":
        reasons.append("UNAVAILABLE_UPSTREAM")
    return ";".join(reasons)


def _parse_text_from_pdf(pdf_bytes):
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        text = "\n".join([page for page in pages if page != ""])
        return text.strip()
    except Exception:
        return ""


def _extract_item_payload(item_url, format_hint):
    session = _get_http_session()
    try:
        _pace_requests("cellar_item_get", INFOCURIA_MIN_INTERVAL_SECONDS)
        response = session.get(item_url, timeout=60)
    except Exception:
        return "", "", ""
    if response.status_code != 200:
        return "", "", ""

    hinted = (format_hint or "").lower()
    content_type = str(response.headers.get("content-type", "")).lower()

    if (
        hinted in {"xhtml", "html", "xml"}
        or "html" in content_type
        or "xml" in content_type
    ):
        raw_markup = response.text
        return get_full_text_from_html(raw_markup).strip(), raw_markup, hinted or "html"
    if hinted in {"pdf", "pdfa2a"} or "pdf" in content_type:
        return _parse_text_from_pdf(response.content), "", "pdf"
    return "", "", hinted


def _choose_best_sector8_item(candidates, language="EN", summary=False):
    if len(candidates) == 0:
        return None

    format_order = SECTOR8_SUMMARY_FORMAT_ORDER if summary else SECTOR8_MAIN_FORMAT_ORDER
    filtered = [
        candidate for candidate in candidates if candidate.get("format") in format_order
    ]
    if len(filtered) == 0:
        return None

    language = language.upper()

    def _rank(candidate):
        candidate_lang = candidate.get("language", "")
        if candidate_lang == language:
            lang_rank = 0
        elif candidate_lang == "":
            lang_rank = 2
        else:
            lang_rank = 1
        fmt_rank = format_order.get(candidate.get("format", ""), 99)
        return (lang_rank, fmt_rank, candidate.get("item_url", ""))

    return sorted(filtered, key=_rank)[0]


def _fetch_sector8_work_uri(celex):
    escaped = _escape_sparql_literal(celex)
    query = f"""
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        select distinct ?doc
        where {{
            ?doc cdm:resource_legal_id_celex ?celex .
            ?doc cdm:resource_legal_id_sector ?sector .
            FILTER(STR(?celex) = "{escaped}")
            FILTER(STR(?sector) = "8")
        }}
        order by asc(str(?doc))
        limit 1
    """
    ret = _query_cellar_sparql(query)
    rows = ret.get("results", {}).get("bindings", []) if isinstance(ret, dict) else []
    if len(rows) == 0:
        return ""
    return rows[0].get("doc", {}).get("value", "")


def _fetch_sector8_summary_work_uris(work_uri):
    query = f"""
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        select distinct ?summary
        where {{
            ?summary cdm:summary_summarizes_work <{work_uri}> .
        }}
        order by asc(str(?summary))
    """
    ret = _query_cellar_sparql(query)
    rows = ret.get("results", {}).get("bindings", []) if isinstance(ret, dict) else []
    return [
        row.get("summary", {}).get("value", "")
        for row in rows
        if row.get("summary", {}).get("value", "") != ""
    ]


def _fetch_sector8_items_for_work(work_uri):
    query = f"""
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        select distinct ?expr ?lang ?mtype ?item
        where {{
            ?expr cdm:expression_belongs_to_work <{work_uri}> .
            OPTIONAL {{ ?expr cdm:expression_uses_language ?lang . }}
            ?man cdm:manifestation_manifests_expression ?expr .
            OPTIONAL {{ ?man cdm:manifestation_type ?mtype . }}
            ?item cdm:item_belongs_to_manifestation ?man .
        }}
    """
    ret = _query_cellar_sparql(query)
    rows = ret.get("results", {}).get("bindings", []) if isinstance(ret, dict) else []
    candidates = []
    for row in rows:
        item_url = row.get("item", {}).get("value", "")
        if item_url == "":
            continue
        mtype = str(row.get("mtype", {}).get("value", "")).lower()
        lang_uri = row.get("lang", {}).get("value", "")
        candidates.append(
            {
                "item_url": item_url,
                "format": mtype,
                "language": _extract_short_lang_from_uri(lang_uri),
            }
        )
    return candidates


def _fetch_sector8_subject_labels(work_uri, language="en"):
    query = f"""
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        prefix skos: <http://www.w3.org/2004/02/skos/core#>
        select distinct ?subject ?label
        where {{
            <{work_uri}> cdm:resource_legal_is_about_subject-matter ?subject .
            OPTIONAL {{
                ?subject skos:prefLabel ?label .
                FILTER(lang(?label) = "{language}")
            }}
        }}
    """
    ret = _query_cellar_sparql(query)
    rows = ret.get("results", {}).get("bindings", []) if isinstance(ret, dict) else []
    labels = []
    for row in rows:
        label = row.get("label", {}).get("value", "")
        if label != "":
            labels.append(label.strip())
        else:
            uri = row.get("subject", {}).get("value", "")
            if uri != "":
                labels.append(uri.rsplit("/", 1)[-1].strip())
    return list(dict.fromkeys([label for label in labels if label != ""]))


def _get_case_data_sector8(celex, language="EN"):
    work_uri = _fetch_sector8_work_uri(celex)

    text = ""
    html = ""
    text_source = ""
    text_language = ""
    text_format = ""
    summary = ""
    summary_source = ""
    summary_language = ""
    keywords = ""
    eurovoc = ""

    if work_uri != "":
        subject_labels = _fetch_sector8_subject_labels(work_uri, language="en")
        keywords = ";".join(subject_labels)
        eurovoc = keywords

        main_candidates = _fetch_sector8_items_for_work(work_uri)
        best_main = _choose_best_sector8_item(
            main_candidates, language=language, summary=False
        )
        if best_main is not None:
            main_text, main_markup, normalized_format = _extract_item_payload(
                best_main["item_url"], best_main["format"]
            )
            text = main_text
            html = (
                main_markup
                if main_markup != ""
                else (f"<pre>{main_text}</pre>" if main_text != "" else "")
            )
            text_source = "CELLAR_ITEM"
            text_language = best_main.get("language", "")
            text_format = normalized_format or best_main.get("format", "")

        summary_candidates = []
        for summary_work in _fetch_sector8_summary_work_uris(work_uri):
            summary_candidates.extend(_fetch_sector8_items_for_work(summary_work))
        best_summary = _choose_best_sector8_item(
            summary_candidates, language=language, summary=True
        )
        if best_summary is not None:
            summary_text, _, _ = _extract_item_payload(
                best_summary["item_url"], best_summary["format"]
            )
            summary = summary_text
            summary_source = "CELLAR_SUMMARY_ITEM" if summary != "" else ""
            summary_language = best_summary.get("language", "") if summary != "" else ""

    missing_reasons = _build_missing_reasons(text=text, summary=summary)

    return {
        "html": html,
        "text": text,
        "summary": summary,
        "keywords": keywords,
        "directory_codes": "",
        "eurovoc": eurovoc,
        "advocate": "",
        "judge": "",
        "affecting_ids": "",
        "affecting_string": "",
        "citations_extra": "",
        "text_source": text_source,
        "text_language": text_language,
        "text_format": text_format,
        "summary_source": summary_source,
        "summary_language": summary_language,
        "sector": "8",
        "missing_reasons": missing_reasons,
    }


def _extract_aff_id_from_suggest_identifier(identifier):
    raw = identifier.split("-")[0]
    match = re.match(r"(?P<aff_id>.+)/(?:P|R)/\d+$", raw)
    if match:
        return match.group("aff_id"), raw
    return "", raw


def _extract_labels(entries, language="en"):
    labels = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("label"), list):
            for item in entry.get("label"):
                if isinstance(item, dict) and language in item:
                    labels.append(item[language])
        if language in entry and isinstance(entry[language], str):
            labels.append(entry[language])
    # Preserve order, remove duplicates.
    return list(dict.fromkeys([label.strip() for label in labels if label.strip()]))


def _extract_text_by_language(multilingual_entries, language="en"):
    lang = language.lower()
    for item in multilingual_entries or []:
        if isinstance(item, dict):
            value = item.get(lang)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for item in multilingual_entries or []:
        if isinstance(item, dict):
            for value in item.values():
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _extract_summary_from_documents(doc_hits, language="en"):
    type_priority = {
        "DDP": 0,
        "DDP_COMM": 1,
        "CONCL": 2,
        "ARRET": 3,
        "ORDONNANCE": 4,
    }
    candidates = []
    for hit in doc_hits or []:
        content = hit.get("content", {}) if isinstance(hit, dict) else {}
        summary_text = _extract_text_by_language(
            content.get("contentML"), language=language
        )
        if summary_text == "":
            continue
        summary_lower = summary_text.lower()
        marker_index = summary_lower.find("summary")
        has_summary_marker = marker_index != -1
        if has_summary_marker:
            summary_text = summary_text[marker_index:]
        doc_type = content.get("docTypeCode", "")
        rank = (0 if has_summary_marker else 1, type_priority.get(doc_type, 99))
        candidates.append((rank, summary_text))
    if len(candidates) == 0:
        return ""
    return sorted(candidates, key=lambda item: item[0])[0][1].strip()


def _resolve_name_by_code(code, entries, language="en"):
    if not isinstance(entries, list) or len(entries) == 0:
        return ""
    selected = None
    if code:
        for entry in entries:
            if isinstance(entry, dict) and entry.get("code") == code:
                selected = entry
                break
    if selected is None:
        selected = entries[0]
    labels = _extract_labels([selected], language=language)
    return ";".join(labels)


_AFFECTING_FIELDS = (
    ("joinAffairs", "joined"),
    ("pourvoiAffIds", "appeal_against"),
    ("originPourvoiIds", "appealed_in"),
    ("reExamenAffIds", "re-examines"),
    ("originReExamanIds", "re-examined_in"),
    ("transfertAffIds", "transfers"),
    ("originTransfertIds", "transferred_from"),
)


def _split_affecting_entry(entry):
    """Return (raw_internal_id, published_id) from an InfoCuria affecting entry.

    Entries look like ``C/0073/24/00000000RP/01/P/01#C-73/24`` — the part
    after ``#`` is the human-readable published case number; the part before
    is InfoCuria's internal procedure id. We surface the clean published id
    in ``affecting_ids`` and the longer descriptive form in ``affecting_string``.
    """
    raw = str(entry).strip()
    if raw == "":
        return "", ""
    if "#" in raw:
        internal, published = raw.split("#", 1)
        return internal.strip(), published.strip()
    return raw, raw


def _collect_affecting(content):
    """Return (affecting_ids, affecting_string) from an InfoCuria result hit.

    - ``affecting_ids``: ``;``-joined list of published case numbers (e.g. ``C-73/24``).
    - ``affecting_string``: ``;``-joined descriptive entries prefixed with the
      relation kind (e.g. ``joined: C-73/24``).
    """
    ids = []
    strings = []
    for field, relation in _AFFECTING_FIELDS:
        vals = content.get(field)
        if not isinstance(vals, list):
            continue
        for entry in vals:
            _, published = _split_affecting_entry(entry)
            if published == "":
                continue
            if published not in ids:
                ids.append(published)
            descriptive = f"{relation}: {published}"
            if descriptive not in strings:
                strings.append(descriptive)
    return ";".join(ids), ";".join(strings)


def _collect_affecting_ids(content):
    """Backwards-compat alias returning only the IDs side of _collect_affecting."""
    ids, _ = _collect_affecting(content)
    return ids


def _choose_best_document(doc_hits, language="EN"):
    candidates = []
    for hit in doc_hits or []:
        content = hit.get("content", {}) if isinstance(hit, dict) else {}
        doc_formats = content.get("docFormats") or []
        if "HTML" not in doc_formats:
            continue
        if not content.get("logicDocId") or not content.get("idProcedure"):
            continue
        candidates.append(content)
    if len(candidates) == 0:
        return None

    type_priority = {
        "ARRET": 0,
        "ORDONNANCE": 1,
        "CONCL": 2,
    }

    def _rank(doc):
        lang_match = 0 if doc.get("docLang") == language else 1
        doc_type = doc.get("docTypeCode", "")
        priority = type_priority.get(doc_type, 99)
        return (lang_match, priority)

    return sorted(candidates, key=_rank)[0]


def _fetch_sector3_xhtml(celex, language="EN"):
    url = f"{CELLAR_REST_BASE}/{celex}"
    auth_lang = (_short_lang_to_authority(language) or "ENG").lower()
    session = _get_http_session()
    last_error = None
    for attempt in range(3):
        try:
            _pace_requests("cellar_rest_get", INFOCURIA_MIN_INTERVAL_SECONDS)
            response = session.get(
                url,
                headers={
                    "Accept": "application/xhtml+xml",
                    "Accept-Language": auth_lang,
                },
                timeout=60,
            )
        except Exception as exc:
            last_error = exc
            _sleep_with_backoff(attempt)
            continue
        if response.status_code == 200:
            return response.text, response.headers.get("Content-Language", auth_lang)
        if response.status_code == 404:
            return "", ""
        _sleep_with_backoff(attempt)
    if last_error:
        return "", ""
    return "", ""


def _get_case_data_sector3(celex, language="EN"):
    xhtml, content_lang = _fetch_sector3_xhtml(celex, language=language)
    text = ""
    html = ""
    text_source = ""
    text_language = ""
    text_format = ""
    if xhtml != "":
        text = get_full_text_from_html(xhtml).strip()
        html = xhtml
        text_source = "CELLAR_REST_XHTML"
        primary_tag = (content_lang or "").split(",")[0].split("-")[0].upper()
        if len(primary_tag) == 3:
            short = _authority_lang_to_short(primary_tag)
        elif len(primary_tag) == 2:
            short = primary_tag
        else:
            short = ""
        text_language = short or language.upper()
        text_format = "xhtml"
    sector_tag = celex[:1] if celex and celex[:1] in {"0", "3"} else "3"
    return {
        "html": html,
        "text": text,
        "summary": "",
        "keywords": "",
        "directory_codes": "",
        "eurovoc": "",
        "advocate": "",
        "judge": "",
        "affecting_ids": "",
        "affecting_string": "",
        "citations_extra": "",
        "text_source": text_source,
        "text_language": text_language,
        "text_format": text_format,
        "summary_source": "",
        "summary_language": "",
        "sector": sector_tag,
        "missing_reasons": _build_missing_reasons(text=text, summary=""),
    }


def _get_case_data_sector6(celex, language="EN"):
    normalized = _normalize_celex(celex)
    if not normalized.startswith("6"):
        return None
    published_id = _published_id_from_celex(normalized)
    if published_id == "":
        return None

    suggest_payload = {
        "searchTerm": published_id,
        "language": language,
        "tabName": "jurisprudence",
    }
    suggest_response = _post_json(INFOCURIA_SUGGEST, suggest_payload)
    if not isinstance(suggest_response, list) or len(suggest_response) == 0:
        return None

    procedure_info = None
    for item in suggest_response:
        info = item.get("procedureDocInfo", {}) if isinstance(item, dict) else {}
        if str(info.get("idPublished", "")).startswith(published_id):
            procedure_info = info
            break
    if procedure_info is None:
        procedure_info = suggest_response[0].get("procedureDocInfo", {})

    if not isinstance(procedure_info, dict) or procedure_info.get("id") is None:
        return None

    aff_id, _ = _extract_aff_id_from_suggest_identifier(procedure_info["id"])
    if aff_id == "":
        return None

    procedures_payload = {
        "affId": aff_id,
        "searchTerm": published_id,
        "tabName": "jurisprudence",
        "language": language,
    }
    procedures = _post_json(INFOCURIA_PROCEDURES, procedures_payload)
    hits = procedures.get("searchHits", []) if isinstance(procedures, dict) else []
    if len(hits) == 0:
        return None

    root_hit = hits[0]
    root_content = root_hit.get("content", {}) if isinstance(root_hit, dict) else {}
    documents = (
        root_hit.get("innerHits", {}).get("document", {}).get("searchHits", [])
        if isinstance(root_hit, dict)
        else []
    )
    selected_doc = _choose_best_document(documents, language=language)
    if selected_doc is None:
        return None

    summary_from_documents = _extract_summary_from_documents(documents, language="en")

    logic_doc_id = str(selected_doc["logicDocId"]).replace("id_", "")
    id_procedure = selected_doc["idProcedure"]
    proc_parts = id_procedure.split("/")
    if len(proc_parts) < 3:
        return None
    jurisdiction = proc_parts[0]
    year = proc_parts[2]
    year = f"20{year}" if len(year) == 2 else year
    process = id_procedure.replace("/", "_")
    doc_lang = selected_doc.get("docLang") or language
    blob_url = INFOCURIA_BLOB_HTML.format(
        jurisdiction=jurisdiction,
        year=year,
        process=process,
        file_name=f"{logic_doc_id}-{doc_lang}-1.html",
    )
    _pace_requests("infocuria_blob_get", INFOCURIA_MIN_INTERVAL_SECONDS)
    html_response = _get_http_session().get(blob_url, timeout=60)
    html = html_response.text if html_response.status_code == 200 else ""

    keywords = ";".join(_extract_labels(root_content.get("matCodeML"), language="en"))
    directory_codes = ";".join(root_content.get("matCode", []) or [])
    summary = summary_from_documents or ";".join(
        _extract_labels(root_content.get("affObjectML"), language="en")
    )
    advocate = _resolve_name_by_code(
        root_content.get("avg"),
        root_content.get("advocateML"),
        language="en",
    )
    judge = _resolve_name_by_code(
        root_content.get("reportingJudge"),
        root_content.get("reportingJudgeML"),
        language="en",
    )
    affecting_ids, affecting_string = _collect_affecting(root_content)
    result_labels = ";".join(
        _extract_labels(root_content.get("procedureResultTypeML"), language="en")
    )
    parties = root_content.get("parties", "")
    citations_extra = ";".join([val for val in [parties, result_labels] if val])

    text = get_full_text_from_html(html) if html != "" else ""
    if summary_from_documents != "":
        summary_source = "INFOCURIA_DOCUMENT_CONTENT"
    elif summary != "":
        summary_source = "INFOCURIA_AFF_OBJECT"
    else:
        summary_source = ""

    return {
        "html": html,
        "text": text,
        "summary": summary,
        "keywords": keywords,
        "directory_codes": directory_codes,
        "eurovoc": keywords,
        "advocate": advocate,
        "judge": judge,
        "affecting_ids": affecting_ids,
        "affecting_string": affecting_string,
        "citations_extra": citations_extra,
        "text_source": "INFOCURIA_BLOB_HTML" if text != "" else "",
        "text_language": str(doc_lang).upper() if doc_lang else language.upper(),
        "text_format": "html" if text != "" else "",
        "summary_source": summary_source,
        "summary_language": "EN" if summary != "" else "",
        "sector": "6",
        "missing_reasons": _build_missing_reasons(text=text, summary=summary),
    }


@lru_cache(maxsize=2048)
def _get_case_data_cached(celex, language="EN"):
    normalized = _normalize_celex(celex)
    if normalized == "":
        return None
    if normalized.startswith("6"):
        return _get_case_data_sector6(normalized, language=language)
    if normalized.startswith("8"):
        return _get_case_data_sector8(normalized, language=language)
    if normalized.startswith("3") or normalized.startswith("0"):
        return _get_case_data_sector3(normalized, language=language)
    return None


def get_case_data_by_celex_id(celex, language="EN"):
    try:
        normalized = _normalize_celex(celex)
        if normalized == "":
            return None
        return _get_case_data_cached(normalized, language=language.upper())
    except Exception:
        return None


def get_legislation_by_celex_id(celex, language="EN"):
    return get_case_data_by_celex_id(celex, language=language)


def is_code(word):
    return word.replace(".", "0").replace("-", "0")[1:].isdigit()


def response_wrapper(link, num=1):
    """
    Wrapped method for requests.get().
    After 10 retries, it gives up and returns a "404" string.
    """
    if num == 10:
        return "404"
    try:
        _pace_requests("generic_get", INFOCURIA_MIN_INTERVAL_SECONDS)
        response = _get_http_session().get(link, timeout=60)
        return response
    except Exception:
        _sleep_with_backoff(num, base=0.3)
        return response_wrapper(link, num + 1)


def get_summary_html(celex):
    """
    This method returns the html of a summary page.
    Uses InfoCuria structured metadata for CJEU cases (sector 6).
    """
    info = get_case_data_by_celex_id(celex, language="EN")
    if not info:
        return "No summary available"
    summary = info.get("summary", "")
    keywords = info.get("keywords", "")
    if summary == "" and keywords == "":
        return "No summary available"
    return f"Keywords\n{keywords}\nSummary\n{summary}".strip()


def get_summary_from_html(html, starting):
    """
    Method used to extract the summary from a html page.
    Cellar specific, uses get_words_from_keywords.
    Currently only walking for celex id's starting with a 6 ( EU cases).

    # This method turns the html code from the summary page into text
    # It has different cases depending on the first character of the CELEX ID
    # Should only be used for summaries extraction
    """
    text = get_full_text_from_html(html)
    if starting == "8":
        return "No summary available"
    elif starting == "6":
        try:
            text2 = text.replace("Summary", "nothing", 1)
            index = text2.index("Summary")
            text2 = text2[index:]
            return text2
        except Exception:
            return text
    return text


def get_keywords_from_html(html, starting):
    """
    Method used to extract the keywords from a html page.
    Cellar specific, uses get_words_from_keywords.
    # This method turns the html code from the summary page into text
    # It has different cases depending on the first character of the CELEX ID
    # Should only be used for summaries extraction
    """
    text = get_full_text_from_html(html)
    if starting == "8":
        text = "No keywords available"
        return text
    elif starting == "6":
        return get_words_from_keywords(text)


def extract_dictionary_from_webservice_query(response):
    """
    Method used for citations extraction from eurlex webservices.
    It reads the SOAP response from the webservices, and adds values to the
    dictionary based on the results. Dictionary is using the celex id of a
    work as key and a list of celex id's of works cited as value.
    """
    text = response.text
    read = xmltodict.parse(text)
    results = read["S:Envelope"]["S:Body"]["searchResults"]["result"]
    dictionary = dict()
    if isinstance(results, list):
        for result in results:
            celex, citing = extract_citations_from_soap(result)
            dictionary[celex] = citing
    else:
        celex, citing = extract_citations_from_soap(results)
        dictionary[celex] = citing
    return dictionary


def extract_citations_from_soap(results):
    """
    Method used for citations extraction from eurlex webservices.
    Reads the individual celex id and documents cited from a single result.
    """
    main_content = results["content"]["NOTICE"]["WORK"]
    celex = main_content["ID_CELEX"].get("VALUE")
    try:
        citing = main_content["WORK_CITES_WORK"]
    except KeyError:
        return celex, ""
    citing_list = list()
    if isinstance(citing, list):
        for cited in citing:
            celex_of_citation = get_citation_celex(cited)
            if celex_of_citation != "":
                citing_list.append(celex_of_citation)
        return celex, ";".join(citing_list)
    else:
        return celex, get_citation_celex(citing)


def get_citation_celex(cited):
    """
    Method used for citations extraction from eurlex webservices.
    Goes thru all of the different id's of the document cited,
    and returns the one that is a celex id.
    """
    identifiers = cited["SAMEAS"]
    if isinstance(identifiers, list):
        for _id in identifiers:
            ident = _id["URI"]["IDENTIFIER"]
            if is_celex_id(ident):
                return ident
    else:
        ident = identifiers["URI"]["IDENTIFIER"]
        if is_celex_id(ident):
            return ident
    return ""


def is_celex_id(_id):
    """
    Method checking if the id passed is a celex id, using regex.
    """
    if _id is None:
        return False
    if prog.match(_id):
        return True
    else:
        return False


def get_words_from_keywords_em(text):
    """
    This method tries to extract only they keywords from a part of
    html page containing it.
    They keywords on the page are always separated by " - " or other
    types of dashes.
    """
    lines = text.split(sep="\n")
    returner = set()
    for line in lines:
        if "—" in line:
            line = line.replace("‛", "")
            line = line.replace("(", "")
            line = line.replace(")", "")
            returner.update(line.split(sep="—"))
        elif "–" in line:
            line = line.replace("‛", "")
            line = line.replace("(", "")
            line = line.replace(")", "")
            returner.update(line.split(sep="–"))
        elif " - " in line:
            line = line.replace("‛", "")
            line = line.replace("(", "")
            line = line.replace(")", "")
            returner.update(line.split(sep=" - "))
    return ";".join(returner)


def get_words_from_keywords(text):
    """
    One of the methods used to extract keywords from summary text.
    """
    if "Keywords" in text:
        try:
            index = text.find("Keywords")
            if "Summary" in text[index : index + 25]:
                text2 = text.replace("Summary", "", 1)
                try:
                    indexer = text2.find("Summary")
                    text = text[index:indexer]
                except Exception:
                    text = text
        except Exception:
            text = text
    else:
        if "Summary" in text:
            index = text.find("Summary")
            text = text[:index]
    return get_words_from_keywords_em(text)


def get_full_text_from_html(html_text):
    """
    This method turns the html code from the summary page into text.
    It has different cases depending on the first character of the CELEX ID.
    Universal method, also replaces all "," with "_".
    """
    # Comma-to-underscore is preserved here for backwards compatibility with
    # the CSV-flattened pipeline. New consumers that need faithful plain text
    # should use get_clean_text_from_html instead.
    text = get_clean_text_from_html(html_text)
    return text.replace(",", "_")


def get_clean_text_from_html(html_text):
    """Plain-text rendering of HTML/XHTML markup, preserving commas.

    Same line/whitespace normalization as get_full_text_from_html, but without
    the legacy comma-to-underscore substitution. Suitable for downstream
    platforms that consume natural-language text directly.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.extract()
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return "\n".join(chunk for chunk in chunks if chunk)


def get_html_text_by_celex_id(id):
    """
    Fetches full HTML case text through InfoCuria endpoints.
    """
    info = get_case_data_by_celex_id(id, language="EN")
    if not info:
        return "404"
    html = info.get("html", "")
    if html:
        return html
    text = info.get("text", "")
    return f"<pre>{text}</pre>" if text else "404"


def get_entire_page(celex):
    """
    Returns a synthetic details page assembled from InfoCuria metadata.
    The text markers are kept compatible with downstream parsers.
    """
    info = get_case_data_by_celex_id(celex, language="EN")
    if not info:
        return "No data available"

    summary = info.get("summary", "")
    keywords = info.get("keywords", "")
    eurovoc = info.get("eurovoc", "")
    directory_codes = info.get("directory_codes", "")
    advocate = info.get("advocate", "")
    judge = info.get("judge", "")
    affecting_strings = info.get("affecting_string", "")
    citations_extra = info.get("citations_extra", "")

    return (
        f"Keywords:\n{keywords}\n"
        f"Summary:\n{summary}\n"
        f"EUROVOC\n{eurovoc}\n"
        f"Subject matter:\n{keywords}\n"
        f"Case law directory code:\n{directory_codes}\n"
        f"Advocate General:{advocate}\n"
        f"Judge-Rapporteur:{judge}\n"
        f"Case affecting:\n{affecting_strings}\n"
        f"Instruments cited in case law:\n{citations_extra}\n"
        "Miscellaneous information"
    )


def get_subject(text):
    """
    This Method gets the subject matter from a fragment
    of code containing them.
    Used for extracting subject matter for cellar cases only.
    """
    try:
        index_matter = text.index("Subject matter:")
        try:
            index_end = text.index(
                "Case law directory code:"
            )  # if this fails then miscellaneous
        except Exception:
            index_end = text.index("Miscellaneous information")
        extracting = text[index_matter + 16 : index_end]
        subject_mat = extracting.split(sep="\n")
        subject = ";".join(subject_mat)
        subject = subject[: len(subject) - 1]
    except Exception:
        subject = ""
    return subject


def get_eurovoc(text):
    """
    This Method extracts all eurovocs, from a fragment containing them.
    Used for extracting eurovoc for cellar cases.
    """
    try:
        start = text.find("EUROVOC")
        try:
            ending = text.find("Subject matter")
        except Exception:
            try:
                ending = text.find("Directory code")
            except Exception:
                try:
                    ending = text.find("Miscellaneous information")
                except Exception:
                    ending = start
        if ending is start:
            return ""
        else:
            text = text[start:ending]
            texts = text.split("\n")
            lists = []
            for t in texts:
                if "EUROVOC" not in t and t != "":
                    lists.append(t)
            return ";".join(lists)
    except Exception:
        return ""


def get_codes(text):
    """
    Method for getting all of the case directory codes for each cellar case.
    Extracts them from a string containing the eurlex website containing
    all document information.
    """
    try:
        index_codes = text.index("Case law directory code:")
        index_end = text.index("Miscellaneous information")
        extracting = text[index_codes + 20 : index_end]
        extracting = extracting.rstrip()
        words = extracting.split()
        codes = [x for x in words if is_code(x)]
        codes_full = list(set(codes))
        codes_result = list()
        indexes = [extracting.find(x) for x in codes_full]
        for x in range(len(codes_full)):
            done = False
            index_start = indexes[x]
            getting_ending = extracting[index_start:]
            words_here = getting_ending.split()
            for words in words_here:
                if words is not words_here[0]:
                    if is_code(words):
                        ending = getting_ending[2:].find(words)
                        done = True
                        break
            if done:
                code_text = getting_ending[:ending]
            else:
                code_text = getting_ending
            codes_result.append(code_text.replace("\n", ""))
        code = ";".join(codes_result)
    except Exception:
        code = ""
    return code


def get_advocate_or_judge(text, phrase):
    """
    :param text: full text of the info page of a case from eur-lex website
    :param phrase: Phrase to search for, works for Advocate General
    and Judge-Rapporteur
    :return: The name of the person with the title of phrase param
    ( if listed on page)
    """
    try:
        index_matter = text.index(phrase)
        extracting = text[index_matter + len(phrase) :]
        extracting = extracting.replace("\n", "", 1)
        ending = extracting.find("\n")
        extracting = extracting[:ending]
        # In case they ever change it to delimiter
        extracting.replace(",", "_")
        subject_mat = extracting.split(sep="_")
        subject_mat = [i.strip() for i in subject_mat]
        return ";".join(subject_mat)
    except Exception:
        return ""


def get_case_affecting(text):
    """
    :param text: full text of the info page of a case from eur-lex website
    :return: The celex id's of case affecting listed + entire string data with
    more information about the case affecting
    """
    phrase = "Case affecting:"
    try:
        index_matter = text.index(phrase)
        extracting = text[index_matter + len(phrase) :]
        extracting = extracting.replace("\n", "", 1)
        phrases = extracting.split(sep="\n")
        full_strings = []
        ids = set()
        for p in phrases:
            if ":" in p:
                break
            else:
                words = p.split()
                if len(words) > 1:
                    for w in words:
                        if is_celex_id(w):
                            ids.add(w)
                    full_strings.append(p)
                else:
                    if len(words) == 1:
                        last = full_strings.pop()
                        last += "_" + p
                        full_strings.append(last)

        return ";".join(ids), ";".join(full_strings)
    except Exception:
        return "", ""


def get_citations_with_extra_info(text):
    """
    :param text: full text of the info page of a case from eur-lex website
    """
    phrase = "Instruments cited in case law:"
    data_list = []
    try:
        index_matter = text.index(phrase)
        extracting = text[index_matter + len(phrase) :]
        extracting = extracting.replace("\n", "", 1)
        sentences = extracting.splitlines()
        for line in sentences:
            words = line.split()
            if is_celex_id(words[0]):
                fixed_line = line.replace(" - ", "-").replace(" ", "_")
                data_list.append(fixed_line)
            else:
                return ";".join(data_list)
    except Exception:
        return ""
