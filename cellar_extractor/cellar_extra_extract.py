import logging

from cellar_extractor.json_to_csv import read_csv
from cellar_extractor.fulltext_saving import add_sections
from cellar_extractor.citations_adder import add_citations_separate


def extra_cellar(data=None, filepath=None, threads=10, username="", password=""):
    """
    Extracts information from a cellar dataset.

    Args:
        data (pandas.DataFrame, optional): The input dataset. If not provided,
        it will be read from the specified filepath.
        filepath (str, optional): The path to the input dataset file.
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
    `filepath`.

    Citation enrichment now always uses the public SPARQL endpoint. EUR-Lex
    webservice credentials are no longer required for extractor completeness.

    The function will add sections to the dataset using the specified
    number of `threads`. If `filepath` is provided,
    the modified dataset will be saved to the same file. Otherwise, the
    modified dataset and a JSON object will be returned.
    """
    if data is None:
        data = read_csv(filepath)
    if username != "" or password != "":
        logging.info(
            "EUR-Lex webservice credentials were provided but are ignored. "
            "Citation enrichment now uses the SPARQL path only."
        )

    add_citations_separate(data, threads)
    if filepath:
        add_sections(data, threads, filepath.replace(".csv", "_fulltext.json"))
        data.to_csv(filepath, index=False)
    else:
        json = add_sections(data, threads)
        return data, json
