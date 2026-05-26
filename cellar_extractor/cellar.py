from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

from cellar_extractor.cellar_extra_extract import extra_cellar
from cellar_extractor.cellar_queries import get_all_eclis, get_raw_cellar_metadata
from cellar_extractor.json_to_csv import json_to_csv_returning
from cellar_extractor.nodes_and_edges import get_nodes_and_edges
from cellar_extractor.persistence import (
    UNSET,
    resolve_output_path,
    resolve_save_enabled,
    write_dataframe_csv,
    write_json,
)

METADATA_BATCH_SIZE = 100
MAX_METADATA_WORKERS = 3


def _build_output_stem(prefix, sd, ed):
    return f"{prefix}_{sd}_{ed}".replace(":", "_")


def _materialize_cellar_output(all_eclis, file_format):
    if file_format == "csv":
        return json_to_csv_returning(all_eclis)
    if file_format == "json":
        return all_eclis
    raise ValueError("file_format must be 'csv' or 'json'")


def _write_cellar_output(result, file_format, output_path):
    if file_format == "csv":
        write_dataframe_csv(result, output_path)
    else:
        write_json(result, output_path)


def _fetch_metadata_batches(eclis, batch_size=METADATA_BATCH_SIZE):
    batches = [eclis[i : i + batch_size] for i in range(0, len(eclis), batch_size)]
    if not batches:
        return {}

    worker_count = min(MAX_METADATA_WORKERS, len(batches))
    batch_results = [None] * len(batches)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(get_raw_cellar_metadata, batch): index
            for index, batch in enumerate(batches)
        }
        for future in tqdm(future_to_index, total=len(future_to_index), colour="GREEN"):
            batch_results[future_to_index[future]] = future.result()

    metadata = {}
    for batch_result in batch_results:
        metadata.update(batch_result)
    return metadata


def get_cellar(
    ed=None,
    save_file=UNSET,
    max_ecli=100,
    sd="2022-05-01",
    file_format="csv",
    output_dir="data",
    output_path=None,
    return_data=None,
    save=None,
):
    """
    Fetch base CELLAR metadata.

    Preferred persistence uses `save` plus `output_path` / `output_dir`.
    The older `save_file` parameter is kept as a deprecated alias.
    """
    if not ed:
        ed = datetime.now().isoformat(timespec="seconds")
    save_enabled = resolve_save_enabled(save=save, save_file=save_file, default=True)
    if return_data is None:
        return_data = not save_enabled
    if not save_enabled:
        return_data = True

    file_name = _build_output_stem("cellar", sd, ed)
    logging.info("\n--- PREPARATION ---\n")
    logging.info(f"Starting from specified start date: {sd}")
    logging.info(f"Up until the specified end date {ed}")
    eclis = get_all_eclis(starting_date=sd, ending_date=ed, limit=max_ecli)
    logging.info(f"Found {len(eclis)} ECLIs")
    if len(eclis) == 0:
        logging.info(f"No data to download found between {sd} and {ed}")
        return False
    all_eclis = _fetch_metadata_batches(eclis)

    result = _materialize_cellar_output(all_eclis, file_format)
    if save_enabled:
        extension = "csv" if file_format == "csv" else "json"
        target = resolve_output_path(
            output_path=output_path,
            output_dir=output_dir,
            default_filename=f"{file_name}.{extension}",
        )
        _write_cellar_output(result, file_format, target)

    logging.info("\n--- DONE ---")
    if return_data:
        return result


def get_cellar_extra(
    ed=None,
    save_file=UNSET,
    max_ecli=100,
    sd="2022-05-01",
    threads=10,
    username="",
    password="",
    output_dir="data",
    metadata_output_path=None,
    fulltext_output_path=None,
    save_metadata=None,
    save_fulltext=None,
    return_data=None,
    save=None,
):
    """
    Fetch enriched CELLAR metadata and fulltext payloads.

    Preferred persistence uses `save` plus explicit metadata/fulltext output
    paths. The older `save_file` parameter is kept as a deprecated alias.
    """
    if not ed:
        ed = datetime.now().isoformat(timespec="seconds")
    save_enabled = resolve_save_enabled(save=save, save_file=save_file, default=True)
    data = get_cellar(ed=ed, save=False, max_ecli=max_ecli, sd=sd, file_format="csv")
    if data is False:
        logging.warning("Cellar extraction unsuccessful")
        return False, False
    logging.info("\n--- START OF EXTRA EXTRACTION ---")
    file_name = _build_output_stem("cellar_extra", sd, ed)

    if save_metadata is None:
        save_metadata = save_enabled
    if save_fulltext is None:
        save_fulltext = save_enabled
    if return_data is None:
        return_data = not (save_metadata or save_fulltext)

    resolved_metadata_path = None
    if save_metadata:
        resolved_metadata_path = resolve_output_path(
            output_path=metadata_output_path,
            output_dir=output_dir,
            default_filename=f"{file_name}.csv",
        )

    resolved_fulltext_path = None
    if save_fulltext:
        resolved_fulltext_path = resolve_output_path(
            output_path=fulltext_output_path,
            output_dir=output_dir,
            default_filename=f"{file_name}_fulltext.json",
        )

    data, json_data = extra_cellar(
        data=data,
        threads=threads,
        username=username,
        password=password,
        metadata_output_path=resolved_metadata_path,
        fulltext_output_path=resolved_fulltext_path,
    )
    logging.info("\n--- DONE ---")

    if return_data:
        return data, json_data


def get_nodes_and_edges_lists(df=None, only_local=False):
    if df is None:
        logging.warning("No dataframe passed!")
        return
    try:
        nodes, edges = get_nodes_and_edges(df, only_local)
    except Exception:
        logging.warning("Something went wrong. Nodes and edges creation unsuccessful.")
        return False, False
    return nodes, edges


def filter_subject_matter(df=None, phrase=None):
    if df is None or phrase is None:
        logging.info("Incorrect input values! \n Returning... \n")
    else:
        try:
            mask = (
                df["subject_matter"]
                .str.lower()
                .str.contains(phrase.lower(), na=False)
            )
            return df[mask]
        except Exception as e:
            logging.warning(e)
            logging.warning("Something went wrong!\n Returning... \n")
            return None
