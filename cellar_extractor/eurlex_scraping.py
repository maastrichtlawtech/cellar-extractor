import time
import re
from functools import lru_cache
import requests
import xmltodict

from bs4 import BeautifulSoup

INFOCURIA_BASE = "https://infocuriaws.curia.europa.eu"
INFOCURIA_SUGGEST = INFOCURIA_BASE + "/elastic-connector/suggest"
INFOCURIA_PROCEDURES = INFOCURIA_BASE + "/elastic-connector/affairId/procedures"
INFOCURIA_BLOB_HTML = (
    INFOCURIA_BASE
    + "/blob/download-file-html/{jurisdiction}/{year}/{process}/{file_name}"
)

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
    for _ in range(retries):
        try:
            response = requests.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:
            last_error = exc
        time.sleep(0.3)
    if last_error:
        raise RuntimeError(f"POST request failed for {url}") from last_error
    return None


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
        summary_text = _extract_text_by_language(content.get("contentML"), language=language)
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


def _collect_affecting_ids(content):
    fields = [
        "joinAffairs",
        "pourvoiAffIds",
        "originPourvoiIds",
        "reExamenAffIds",
        "originReExamanIds",
        "transfertAffIds",
        "originTransfertIds",
    ]
    ids = []
    for field in fields:
        vals = content.get(field)
        if isinstance(vals, list):
            ids.extend([str(val).strip() for val in vals if str(val).strip() != ""])
    return ";".join(list(dict.fromkeys(ids)))


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


@lru_cache(maxsize=2048)
def _get_case_data_cached(celex, language="EN"):
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
        root_hit.get("innerHits", {})
        .get("document", {})
        .get("searchHits", [])
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
    html_response = requests.get(blob_url, timeout=60)
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
    affecting_ids = _collect_affecting_ids(root_content)
    result_labels = ";".join(
        _extract_labels(root_content.get("procedureResultTypeML"), language="en")
    )
    parties = root_content.get("parties", "")
    citations_extra = ";".join([val for val in [parties, result_labels] if val])

    return {
        "html": html,
        "summary": summary,
        "keywords": keywords,
        "directory_codes": directory_codes,
        "eurovoc": keywords,
        "advocate": advocate,
        "judge": judge,
        "affecting_ids": affecting_ids,
        "affecting_strings": affecting_ids,
        "citations_extra": citations_extra,
    }


def get_case_data_by_celex_id(celex, language="EN"):
    try:
        normalized = _normalize_celex(celex)
        if normalized == "":
            return None
        return _get_case_data_cached(normalized, language=language.upper())
    except Exception:
        return None


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
        response = requests.get(link, timeout=60)
        return response
    except Exception:
        time.sleep(0.5 * num)
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
    # This method turns the html code from the summary page into text
    # It has different cases depending on the first character of the CELEX ID
    # Should only be used for summaries extraction
    soup = BeautifulSoup(html_text, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()  # rip it out
    text = soup.get_text()
    # break into lines and remove leading and trailing space on each
    lines = (line.strip() for line in text.splitlines())
    # break multi-headlines into a line each
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # drop blank lines
    text = "\n".join(chunk for chunk in chunks if chunk)
    text = text.replace(",", "_")
    return text


def get_html_text_by_celex_id(id):
    """
    Fetches full HTML case text through InfoCuria endpoints.
    """
    info = get_case_data_by_celex_id(id, language="EN")
    if not info:
        return "404"
    html = info.get("html", "")
    return html if html else "404"


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
    affecting_strings = info.get("affecting_strings", "")
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
