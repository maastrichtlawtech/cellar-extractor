"""
CDM-triple → DataFrame flattening.

Input shape: ``{key: {predicate_local_part: [values, ...]}}`` produced by
``cellar_queries.get_raw_cellar_metadata`` (key = ECLI) or
``cellar_queries.get_raw_cellar_metadata_by_celex`` (key = CELEX).

Output shape: a pandas DataFrame whose columns are canonical snake_case names
(per ``cellar_extractor.schema``). CDM predicates without a canonical mapping
still surface — under their stable URI-local-part as a snake_case fallback —
so we never silently drop data the endpoint actually returned.

Multi-valued predicates collapse to a single ``;``-joined string per row.
Missing values are left empty (pandas reads them as NaN).
"""

import csv
import logging
import sys
import warnings
from io import StringIO

import pandas as pd

from cellar_extractor.persistence import ensure_parent_dir
from cellar_extractor.schema import CANONICAL_COLUMNS, cdm_canonical_name


warnings.filterwarnings("ignore")


def _format_value(values):
    """Collapse a list of triple objects into a single CSV-friendly cell."""
    if values is None:
        return ""
    if not isinstance(values, list):
        return str(values).strip()
    out = []
    for v in values:
        s = str(v).strip()
        if s == "":
            continue
        out.append(s)
    return ";".join(out)


def _row_for_record(predicate_map):
    """Map one record's predicate dict to a {canonical_name: cell_value} dict."""
    row = {}
    for predicate_local, values in predicate_map.items():
        canonical = cdm_canonical_name(predicate_local)
        if canonical is None:
            continue
        cell = _format_value(values)
        if cell == "":
            continue
        # If two upstream predicates collide on the same canonical name, append
        # rather than clobber. Should be rare; preserves data over surprise.
        if canonical in row and row[canonical] != cell:
            row[canonical] = ";".join(filter(None, [row[canonical], cell]))
        else:
            row[canonical] = cell
    return row


def json_to_csv(json_data):
    """
    Flatten a CDM metadata dict to a list of rows aligned with the canonical
    schema.

    Column ordering: every key in CANONICAL_COLUMNS first (stable contract),
    then any discovered (non-canonical) predicates that the SPARQL endpoint
    returned for at least one row, in alphabetic order. Empty string is used
    for unpopulated cells (pandas reads it as NaN, which is the JSON null
    equivalent).
    """
    rows = [_row_for_record(json_data[key]) for key in json_data]
    discovered = sorted(
        {col for row in rows for col in row.keys() if col not in CANONICAL_COLUMNS}
    )
    columns = list(CANONICAL_COLUMNS) + discovered
    matrix = [[row.get(col, "") for col in columns] for row in rows]
    return columns, matrix


def create_csv(output_path, encoding="UTF8", data=None):
    """Write a CDM metadata dict to a CSV file using the canonical schema."""
    if data is None or data == "":
        return
    columns, matrix = json_to_csv(data)
    target = ensure_parent_dir(output_path)
    with target.open("w", encoding=encoding, newline="") as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(columns)
        csv_writer.writerows(matrix)


def read_csv(file_path):
    try:
        # Force string dtypes so the canonical schema's type contracts are
        # preserved — pandas would otherwise infer numeric for sector ("3"),
        # year_of_resource ("2024"), etc., breaking string-typed comparisons.
        # Downstream consumers cast based on FIELD_MANIFEST.
        return pd.read_csv(file_path, sep=",", encoding="utf-8", dtype=str)
    except Exception:
        logging.info("Something went wrong when trying to open the csv file!")
        logging.info(f" The path to the file was {file_path}")
        sys.exit(2)


def create_csv_returning(columns, matrix):
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows(matrix)
    buf.seek(0)
    return read_csv(buf)


def json_to_csv_returning(json_data):
    if not json_data:
        logging.info(
            "Error reading json file. Please make sure json file exists and contains data."
        )
        return False
    columns, matrix = json_to_csv(json_data)
    if not matrix:
        logging.info("Error creating dataframe. Data is empty.")
        return False
    return create_csv_returning(columns, matrix)


def json_to_csv_main(json_data, filepath):
    warnings.warn(
        "`json_to_csv_main` is deprecated; use `create_csv(output_path=..., data=json_data)` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not json_data:
        logging.info(
            "Error reading json file. Please make sure json file exists and contains data."
        )
        return False
    create_csv(output_path=filepath, encoding="UTF8", data=json_data)
    return True
