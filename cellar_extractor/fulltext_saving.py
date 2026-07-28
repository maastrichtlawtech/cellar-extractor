import json
import threading
import time
import warnings
import math
import pandas as pd
from cellar_extractor.eurlex_scraping import (
    get_case_data_by_celex_id,
    get_html_text_by_celex_id,
    get_full_text_from_html,
    get_summary_html,
    get_keywords_from_html,
    get_summary_from_html,
    get_entire_page,
    get_codes,
    get_eurovoc,
    get_advocate_or_judge,
    get_case_affecting,
    get_citations_with_extra_info,
)
from cellar_extractor.persistence import write_json
from tqdm import tqdm

MAX_FULLTEXT_WORKERS = 6


def _build_fulltext_records(infocuria_data, celex, ecli, missing_reasons_value):
    """Convert one CELEX's ``get_case_data_by_celex_id`` result into a list
    of JSON-ready records, one per language.

    * If ``infocuria_data["fulltexts"]`` is present and non-empty, emit one
      record per language entry.
    * If the list exists but is empty (the case had no recoverable body in
      any language), emit a single placeholder record so the ECLI is still
      represented in ``fulltexts.parquet`` (carries the missing-reasons trail).
    * If no ``fulltexts`` list is present at all (legacy single-language
      handlers, test stubs, etc.), fall back to the top-level
      ``text`` / ``text_source`` / ``text_language`` / ``text_format`` fields —
      backwards-compatible.

    Each output record has the shape::

        {celex, ecli, text, text_source, text_language, text_format,
         missing_reasons}

    """
    if not isinstance(infocuria_data, dict):
        return []

    fulltexts = infocuria_data.get("fulltexts")
    if fulltexts is None:
        # Legacy single-language shape.
        return [
            {
                "celex": str(celex),
                "ecli": ecli,
                "text": infocuria_data.get("text", ""),
                "text_source": infocuria_data.get("text_source", ""),
                "text_language": infocuria_data.get("text_language", ""),
                "text_format": infocuria_data.get("text_format", ""),
                "missing_reasons": missing_reasons_value,
            }
        ]

    if not fulltexts:
        # Multi-language shape but empty — emit a single placeholder so the
        # ECLI doesn't silently disappear from the fulltexts output.
        return [
            {
                "celex": str(celex),
                "ecli": ecli,
                "text": "",
                "text_source": "",
                "text_language": "",
                "text_format": "",
                "missing_reasons": missing_reasons_value,
            }
        ]

    out = []
    for entry in fulltexts:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "celex": str(celex),
                "ecli": ecli,
                "text": entry.get("text", ""),
                "text_source": entry.get("text_source", ""),
                "text_language": entry.get("text_language", ""),
                "text_format": entry.get("text_format", ""),
                "missing_reasons": missing_reasons_value,
            }
        )
    return out


def execute_sections_threads(
    celex,
    eclis,
    source_indices,
    start,
    list_sum,
    list_key,
    list_full,
    list_codes,
    list_eurovoc,
    list_adv,
    list_judge,
    list_affecting_id,
    list_affecting_str,
    list_citations_extra,
    list_fulltext_source,
    list_summary_source,
    list_missing_reasons,
    progress_bar,
):
    """
    This is the method executed by individual threads by the add_sections
    method.
    The big dataset is divided in parts, each thread gets its portion of work
    to do.
    They add their portions of columns to corresponding lists,
    after all the threads are done the individual parts are put together.
    """
    _sum = pd.Series([], dtype="string")
    key = pd.Series([], dtype="string")
    full = list()
    case_codes = pd.Series([], dtype="string")
    eurovocs = pd.Series([], dtype="string")
    adv_general = pd.Series([], dtype="string")
    judge_rapporteur = pd.Series([], dtype="string")
    affecting_id = pd.Series([], dtype="string")
    affecting_str = pd.Series([], dtype="string")
    citations_extra = pd.Series([], dtype="string")
    fulltext_source = pd.Series([], dtype="string")
    summary_source = pd.Series([], dtype="string")
    missing_reasons = pd.Series([], dtype="string")
    for i in range(len(celex)):
        j = start + i
        row_index = source_indices[j]
        _id = celex.iloc[i]
        ecli = eclis.iloc[i]
        infocuria_data = get_case_data_by_celex_id(_id, language="EN")
        if infocuria_data:
            text = infocuria_data.get("text", "")
            if text == "":
                html = infocuria_data.get("html", "")
                text = get_full_text_from_html(html) if html else ""
            summary_value = infocuria_data.get("summary", "")
            keyword_value = infocuria_data.get("keywords", "")
            text_source_value = infocuria_data.get("text_source", "")
            summary_source_value = infocuria_data.get("summary_source", "")
            if text_source_value == "" and text != "":
                text_source_value = "EXTRACTOR_FALLBACK_TEXT"
            if summary_source_value == "" and summary_value != "":
                summary_source_value = "EXTRACTOR_FALLBACK_SUMMARY"

            reasons = [
                reason
                for reason in str(infocuria_data.get("missing_reasons", "")).split(";")
                if reason != ""
            ]
            if text == "" and "FULLTEXT_UNAVAILABLE_UPSTREAM" not in reasons:
                reasons.append("FULLTEXT_UNAVAILABLE_UPSTREAM")
            if summary_value == "" and "SUMMARY_UNAVAILABLE_UPSTREAM" not in reasons:
                reasons.append("SUMMARY_UNAVAILABLE_UPSTREAM")
            if (
                text == ""
                and summary_value == ""
                and "UNAVAILABLE_UPSTREAM" not in reasons
            ):
                reasons.append("UNAVAILABLE_UPSTREAM")
            reasons_value = ";".join(dict.fromkeys(reasons))

            # Multi-language fanout: if the handler populated a `fulltexts`
            # list, emit one row per language (and stamp the same
            # missing_reasons on every row). Otherwise fall back to the
            # single-row legacy shape via _build_fulltext_records.
            #
            # Replace the chosen "primary" text with the post-fallback `text`
            # we computed above (the legacy path applies extractor fallback
            # extraction when the upstream text was empty) so we don't lose
            # that behaviour for the primary entry.
            data_for_records = dict(infocuria_data)
            data_for_records["text_source"] = text_source_value
            data_for_records["text"] = text
            full.extend(
                _build_fulltext_records(
                    data_for_records,
                    celex=_id,
                    ecli=ecli,
                    missing_reasons_value=reasons_value,
                )
            )
            key[row_index] = keyword_value
            _sum[row_index] = summary_value
            eurovocs[row_index] = infocuria_data.get("eurovoc", "")
            case_codes[row_index] = infocuria_data.get("directory_codes", "")
            adv_general[row_index] = infocuria_data.get("advocate", "")
            affecting_id[row_index] = infocuria_data.get("affecting_ids", "")
            affecting_str[row_index] = infocuria_data.get("affecting_string", "")
            judge_rapporteur[row_index] = infocuria_data.get("judge", "")
            citations_extra[row_index] = infocuria_data.get("citations_extra", "")
            fulltext_source[row_index] = text_source_value
            summary_source[row_index] = summary_source_value
            missing_reasons[row_index] = reasons_value
            progress_bar.update(1)
            continue

        html = get_html_text_by_celex_id(_id)
        text = ""
        if html != "404":
            text = get_full_text_from_html(html)
        summary_source_value = ""
        summary = get_summary_html(_id)
        if summary != "No summary available":
            text = get_keywords_from_html(summary, _id[0])
            text2 = get_summary_from_html(summary, _id[0])
            key[row_index] = text
            _sum[row_index] = text2
            summary_source_value = "LEGACY_EURLEX_SUMMARY_HTML"
        else:
            key[row_index] = ""
            _sum[row_index] = ""
            text2 = ""
        entire_page = get_entire_page(_id)
        text = get_full_text_from_html(entire_page)
        if entire_page != "No data available":
            code = get_codes(text)
            eurovoc = get_eurovoc(text)
            adv = get_advocate_or_judge(text, "Advocate General:")
            judge = get_advocate_or_judge(text, "Judge-Rapporteur:")
            ids_affecting, strings_affecting = get_case_affecting(text)
            citation_extra = get_citations_with_extra_info(text)
        else:
            code = ""
            eurovoc = ""
            adv = ""
            judge = ""
            ids_affecting = ""
            strings_affecting = ""
            citation_extra = ""

        eurovocs[row_index] = eurovoc
        case_codes[row_index] = code
        adv_general[row_index] = adv
        affecting_id[row_index] = ids_affecting
        affecting_str[row_index] = strings_affecting
        judge_rapporteur[row_index] = judge
        citations_extra[row_index] = citation_extra
        fulltext_source_value = "LEGACY_EURLEX_HTML" if html != "404" else ""
        reason_values = []
        if html == "404":
            reason_values.append("FULLTEXT_UNAVAILABLE_UPSTREAM")
        if text2 == "":
            reason_values.append("SUMMARY_UNAVAILABLE_UPSTREAM")
        if html == "404" and text2 == "":
            reason_values.append("UNAVAILABLE_UPSTREAM")
        reasons_value = ";".join(reason_values)
        fulltext_source[row_index] = fulltext_source_value
        summary_source[row_index] = summary_source_value
        missing_reasons[row_index] = reasons_value
        json_text = {
            "celex": str(_id),
            "ecli": ecli,
            "text": "" if html == "404" else get_full_text_from_html(html),
            "text_source": fulltext_source_value,
            "text_language": "EN" if html != "404" else "",
            "text_format": "html" if html != "404" else "",
            "missing_reasons": reasons_value,
        }
        full.append(json_text)
        progress_bar.update(1)

    list_sum.append(_sum)
    list_key.append(key)
    list_full.append(full)
    list_codes.append(case_codes)
    list_eurovoc.append(eurovocs)
    list_adv.append(adv_general)
    list_judge.append(judge_rapporteur)
    list_affecting_id.append(affecting_id)
    list_affecting_str.append(affecting_str)
    list_citations_extra.append(citations_extra)
    list_fulltext_source.append(fulltext_source)
    list_summary_source.append(summary_source)
    list_missing_reasons.append(missing_reasons)


def add_sections(
    data,
    threads,
    output_path=None,
    json_filepath=None,
    fulltext_output_path=None,
):
    """
    This method adds the following sections to a pandas dataframe,
    as separate columns:
    Full Text
    Case law directory codes
    Keywords
    Summary
    Advocate General
    Judge Rapporteur
    Case affecting (CELEX ID)
    Case affecting string (entire str with more info)

    Method is cellar-specific, scraping html from
    https://eur-lex.europa.eu/homepage.html.
    It operates with multiple threads, using that feature is recommended
    as it speeds up the entire process.

    Preferred persistence uses `output_path`. The older `json_filepath`
    and `fulltext_output_path` parameters are kept as deprecated aliases.
    """
    source_indices = data.index.tolist()
    celex = data.loc[:, "celex"].reset_index(drop=True)
    eclis = data.loc[:, "ecli"].reset_index(drop=True)
    length = celex.size
    time.sleep(1)
    _bar = tqdm(
        total=length,
        colour="GREEN",
        miniters=max(1, int(length / 100)) if length else 1,
        position=0,
        leave=True,
        maxinterval=10000,
    )
    worker_count = min(max(1, threads), MAX_FULLTEXT_WORKERS, length) if length else 1
    at_once_threads = max(1, math.ceil(length / worker_count)) if length else 1
    threads = []
    list_sum = []
    list_key = []
    list_full = []
    list_codes = []
    list_eurovoc = []
    list_adv = []
    list_judge = []
    list_affecting_id = []
    list_affecting_str = []
    list_citations_extra = []
    list_fulltext_source = []
    list_summary_source = []
    list_missing_reasons = []
    for i in range(0, length, at_once_threads):
        curr_celex = celex[i : (i + at_once_threads)]
        curr_ecli = eclis[i : (i + at_once_threads)]
        t = threading.Thread(
            target=execute_sections_threads,
            args=(
                curr_celex,
                curr_ecli,
                source_indices,
                i,
                list_sum,
                list_key,
                list_full,
                list_codes,
                list_eurovoc,
                list_adv,
                list_judge,
                list_affecting_id,
                list_affecting_str,
                list_citations_extra,
                list_fulltext_source,
                list_summary_source,
                list_missing_reasons,
                _bar,
            ),
        )
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    add_column_frow_list(data, "summary", list_sum)
    add_column_frow_list(data, "keywords", list_key)
    add_column_frow_list(data, "eurovoc", list_eurovoc)
    add_column_frow_list(data, "directory_codes", list_codes)
    add_column_frow_list(data, "advocate_general", list_adv)
    add_column_frow_list(data, "judge_rapporteur", list_judge)
    add_column_frow_list(data, "affecting_ids", list_affecting_id)
    add_column_frow_list(data, "affecting_string", list_affecting_str)
    add_column_frow_list(data, "citations_extra_info", list_citations_extra)
    add_column_frow_list(data, "fulltext_source", list_fulltext_source)
    add_column_frow_list(data, "summary_source", list_summary_source)
    add_column_frow_list(data, "missing_reasons", list_missing_reasons)
    json_file = []
    for _item in list_full:
        if len(_item) > 0:
            json_file.extend(_item)
    if json_filepath is not None:
        warnings.warn(
            "`json_filepath` is deprecated; use `output_path` instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if output_path is None:
            output_path = json_filepath
    if fulltext_output_path is not None:
        warnings.warn(
            "`fulltext_output_path` is deprecated; use `output_path` instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if output_path is None:
            output_path = fulltext_output_path

    if output_path:
        write_json(json_file, output_path)
    return json_file


def add_column_frow_list(data, name, list):
    """Add or replace a column on the enriched dataframe.

    The canonical schema in cellar_extractor.schema pre-populates the row with
    every contracted column (filled with None), so by the time enrichment
    runs the column may already exist. Drop it first then insert so we always
    write enrichment values without colliding.
    """
    column = pd.Series([], dtype="string")
    for _item in list:
        column = pd.concat([column, _item])
    column.sort_index(inplace=True)
    if name in data.columns:
        data.drop(columns=[name], inplace=True)
    data.insert(1, name, column)
