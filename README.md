# Cellar Extractor

`cellar-extractor` is a Python library for building enriched EUR-Lex / CELLAR case-law datasets.

It starts from CELLAR metadata and then enriches:

- citation edges
- summaries and keywords
- full text
- sector-specific metadata
- graph-ready node/edge projections

The extractor is currently centered on:

- **sector 6** case law: CJEU-style material via InfoCuria
- **sector 8** case law: mixed / national-case-law material via CELLAR RDF + item downloads

## Installation

```bash
pip install cellar-extractor
```

Python `>= 3.9`.

## What The Project Does

The main workflow has two stages.

1. `get_cellar(...)`
   - fetches the base CELLAR corpus
   - returns CSV-like dataframe output or JSON-like dictionary output
2. `get_cellar_extra(...)`
   - enriches that corpus with citations, full text, summaries, keywords, provenance, and missing-data flags

The citation graph is now extracted through the public CELLAR SPARQL endpoint. Legacy EUR-Lex SOAP webservice support is kept only for validation tests and is not part of the production path anymore.

## Data Sources By Type

| Need | Source |
| --- | --- |
| Base corpus metadata | CELLAR SPARQL |
| Citation edges (`citing`, `cited_by`) | CELLAR SPARQL |
| Sector 6 full text and structured metadata | InfoCuria |
| Sector 8 full text and summaries | CELLAR RDF + downloadable `item` manifestations |
| Legacy citation comparison only | EUR-Lex SOAP webservice |

## Quick Start

### 1. Fetch Base CELLAR Metadata

```python
import cellar_extractor as cell

df = cell.get_cellar(
    save_file="n",
    file_format="csv",
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    max_ecli=100,
)
```

Returns a dataframe with base metadata such as CELEX, ECLI, type, dates, and subject-matter-related fields.

### 2. Fetch The Enriched Dataset

```python
import cellar_extractor as cell

extra_df, fulltext = cell.get_cellar_extra(
    save_file="n",
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    max_ecli=100,
    threads=4,
)
```

Returns:

- `extra_df`: enriched dataframe
- `fulltext`: list of JSON rows containing extracted text and provenance

### 3. Build A Citation Graph

```python
import cellar_extractor as cell

nodes, edges = cell.get_nodes_and_edges_lists(extra_df, only_local=True)
```

`only_local=True` keeps only edges whose target CELEX is also present in `extra_df`.

### 4. Filter By Subject Matter

```python
filtered = cell.filter_subject_matter(extra_df, "competition")
```

## Full-Scrape Strategy

If you want the largest reproducible scrape, do not run one enormous date range blindly. Use bounded windows and persist each window.

Recommended approach:

1. choose a date window by `sd` / `ed`
2. run `get_cellar(...)` or `get_cellar_extra(...)`
3. save outputs to disk
4. repeat for the next window
5. concatenate downstream

Practical guidance:

- use month-sized or week-sized windows for stability
- keep `threads` moderate, typically `4` to `10`
- use `save_file="y"` for long runs
- keep the fulltext JSON files; they are the canonical extracted text output

Example file-based run:

```python
import cellar_extractor as cell

cell.get_cellar_extra(
    save_file="y",
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    max_ecli=5000,
    threads=6,
)
```

This writes into `data/`:

- a CSV with the enriched tabular dataset
- a `_fulltext.json` file with the text rows

## Main Outputs

`get_cellar_extra(...)` produces:

1. an enriched dataframe / CSV
2. a fulltext JSON list / file

### Important Enriched DataFrame Columns

- `citing`
- `cited_by`
- `celex_summary`
- `celex_keywords`
- `celex_directory_codes`
- `celex_eurovoc`
- `advocate_general`
- `judge_rapporteur`
- `affecting_ids`
- `affecting_strings`
- `citations_extra_info`
- `fulltext_source`
- `summary_source`
- `missing_reasons`

### Important Fulltext JSON Fields

- `celex`
- `ecli`
- `text`
- `text_source`
- `text_language`
- `text_format`
- `missing_reasons`

## Completeness Rules

The extractor does not treat empty values as silent success.

Important cases:

- if citation data exists, it should populate `citing` / `cited_by`
- if a document has no citation edges, the columns still exist and are empty
- if full text or summary is not available upstream, `missing_reasons` should reflect that

Typical `missing_reasons` values:

- `FULLTEXT_UNAVAILABLE_UPSTREAM`
- `SUMMARY_UNAVAILABLE_UPSTREAM`
- `UNAVAILABLE_UPSTREAM`

Sector 8 is still **best effort** because upstream availability is uneven, but the extractor now flags absence explicitly instead of implying completeness.

## Public API Reference

### Root-Level Package API

Imported from [`cellar_extractor/__init__.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/__init__.py):

| Function / class | Purpose |
| --- | --- |
| `get_cellar(...)` | Fetch base CELLAR metadata |
| `get_cellar_extra(...)` | Fetch enriched metadata + full text |
| `get_nodes_and_edges_lists(df, only_local=False)` | Build citation graph lists |
| `filter_subject_matter(df, phrase)` | Filter dataframe by subject phrase |
| `FetchOperativePart` | Extract operative part from a single case document |
| `Writing` | Write operative-part outputs to CSV / JSON / TXT |

### Core Modules

#### [`cellar_extractor/cellar.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar.py)

- `get_cellar(ed=None, save_file="y", max_ecli=100, sd="2022-05-01", file_format="csv")`
- `get_cellar_extra(ed=None, save_file="y", max_ecli=100, sd="2022-05-01", threads=10, username="", password="")`
- `get_nodes_and_edges_lists(df=None, only_local=False)`
- `filter_subject_matter(df=None, phrase=None)`

Notes:

- `username` / `password` are legacy compatibility parameters and no longer change the extraction path

#### [`cellar_extractor/citations_adder.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/citations_adder.py)

- `add_citations_separate(data, threads)`: production citation enrichment
- `add_citations_separate_webservice(data, username, password)`: deprecated legacy comparison path
- `add_citations(data, threads)`: older citation replacement helper

#### [`cellar_extractor/fulltext_saving.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/fulltext_saving.py)

- `add_sections(data, threads, json_filepath=None)`: enriches summaries, keywords, text metadata, provenance, and missing-data flags

#### [`cellar_extractor/eurlex_scraping.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/eurlex_scraping.py)

Main higher-level adapter functions:

- `get_case_data_by_celex_id(celex, language="EN")`
- `get_html_text_by_celex_id(id)`
- `get_summary_html(celex)`
- `get_full_text_from_html(html_text)`

This module contains the sector-aware source logic for InfoCuria and CELLAR item retrieval.

#### [`cellar_extractor/sparql.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/sparql.py)

- `get_citations(source_celex, cites_depth=1, cited_depth=1, max_retries=3)`
- `get_citations_csv(celex, max_retries=3)`
- `get_citing(celex, cites_depth, max_retries=3)`
- `get_cited(celex, cited_depth, max_retries=3)`
- `run_eurlex_webservice_query(query_input, username, password)` for legacy SOAP validation only

#### [`cellar_extractor/cellar_sparql_queries.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar_sparql_queries.py)

Advanced query helper class:

- `CellarSparqlQuery`
  - `get_endorsements()`
  - `get_subjects()`
  - `get_parties()`
  - `get_keywords()`
  - `get_citations()`
  - `get_grounds()`

#### [`cellar_extractor/operative_extractions.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/operative_extractions.py)

Classes:

- `FetchOperativePart`
- `Writing`

Use this path when you want operative-part extraction for individual documents rather than the full dataset pipeline.

## Upstream Endpoints Used

These are the upstream systems the extractor relies on.

| Endpoint family | Used for |
| --- | --- |
| CELLAR SPARQL `https://publications.europa.eu/webapi/rdf/sparql` | corpus discovery, metadata, citation edges |
| InfoCuria `https://infocuriaws.curia.europa.eu/...` | sector 6 text and metadata |
| InfoCuria `https://infocuria.curia.europa.eu/document/...` | sector 6 document HTML |
| CELLAR resource/item URLs under `https://publications.europa.eu/resource/cellar/...` | sector 8 downloadable text / summary manifestations |
| EUR-Lex SOAP `https://eur-lex.europa.eu/EURLexWebService?wsdl` | legacy redundancy tests only |

## Tests

### Fast Local Suite

```bash
pytest -q
```

### Live Integration Flags

- `RUN_INFOCURIA_INTEGRATION=1`
- `RUN_SECTOR8_INTEGRATION=1`
- `RUN_CITATION_INTEGRATION=1`

Examples:

```bash
RUN_INFOCURIA_INTEGRATION=1 pytest -q tests/test_infocuria_integration.py
RUN_SECTOR8_INTEGRATION=1 pytest -q tests/test_sector8_integration.py
RUN_CITATION_INTEGRATION=1 pytest -q tests/test_citation_graph_integration.py
```

### Legacy Webservice Tests

Only needed if you want to re-check SOAP redundancy:

```bash
pytest -q tests/test_webservice_credentials_integration.py tests/test_webservice_redundancy_integration.py
```

If used, credentials are read from `.env`:

```env
EURLEX_WEBSERVICE_USERNAME=
EURLEX_WEBSERVICE_PASSWORD=
```

These credentials are **not required** for normal extraction.

## Troubleshooting

### `missing_reasons` is populated

That means the extractor could not find the requested upstream content. This is expected when upstream does not expose a summary or full text for the document.

### Citation columns are empty

Check:

- that the document actually has graph relations upstream
- the live SPARQL endpoint availability
- whether you are looking at a very small or isolated sample

### Sector 8 feels sparse

That is usually an upstream availability issue, not a silent extractor failure. Sector 8 is intentionally handled as best effort with explicit flags.

## License

[Apache License 2.0](https://opensource.org/licenses/Apache-2.0)
