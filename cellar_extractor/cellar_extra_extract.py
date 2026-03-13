import logging
import warnings

from cellar_extractor.json_to_csv import read_csv
from cellar_extractor.fulltext_saving import add_sections
from cellar_extractor.citations_adder import add_citations_separate
from cellar_extractor.persistence import write_dataframe_csv


def extra_cellar(
    data=None,
    filepath=None,
    input_path=None,
    threads=10,
    username="",
    password="",
    metadata_output_path=None,
    fulltext_output_path=None,
):
    """
    Extracts information from a cellar dataset.

    Args:
        data (pandas.DataFrame, optional): The input dataset. If not provided,
        it will be read from the specified input path.
        filepath (str, optional): Deprecated alias for `input_path`.
        input_path (str, optional): The path to the input dataset file.
        If provided, the data will be read from this file.
        threads (int, optional): The number of threads to use for parallel
        processing. Default is 10.
        username (str, optional): Deprecated and ignored. Kept for backward
        compatibility with older callers.
        password (str, optional): Deprecated and ignored. Kept for backward
        compatibility with older callers.

    Returns:
        tuple: A tuple containing the modified dataset and a JSON object.

    If `data` is not provided, the dataset will be read from the specified
    `input_path`.

    Citation enrichment now always uses the public SPARQL endpoint. EUR-Lex
    webservice credentials are no longer required for extractor completeness.

    The function will add sections to the dataset using the specified
    number of `threads`. Metadata CSV and full-text JSON persistence are
    independently controlled through `metadata_output_path` and
    `fulltext_output_path`. When neither is provided, the function only
    returns in-memory outputs.
    """
    if filepath is not None:
        warnings.warn(
            "`filepath` is deprecated; use `input_path` instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if input_path is None:
            input_path = filepath
    if data is None:
        data = read_csv(input_path)
    if input_path and metadata_output_path is None:
        metadata_output_path = input_path
    if input_path and fulltext_output_path is None:
        fulltext_output_path = input_path.replace(".csv", "_fulltext.json")
    if username != "" or password != "":
        logging.info(
            "EUR-Lex webservice credentials were provided but are ignored. "
            "Citation enrichment now uses the SPARQL path only."
        )

    add_citations_separate(data, threads)
    json_data = add_sections(data, threads, output_path=fulltext_output_path)
    if metadata_output_path:
        write_dataframe_csv(data, metadata_output_path)
    return data, json_data
