# Cellar Extractor

[![CI](https://github.com/maastrichtlawtech/cellar-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/maastrichtlawtech/cellar-extractor/actions/workflows/ci.yml)
![Coverage](https://img.shields.io/badge/coverage-50%25-yellow)

A Python library for extracting CELLAR case law data from EUR-Lex.

This library contains functions to get CELLAR case law data from the EUR-Lex SPARQL endpoint and enrich additional information from InfoCuria and CELLAR item sources.

## Version

Python `3.9+`

## Tests

- CI: the badge above tracks the default supported test workflow
- Coverage: the badge above tracks the default local test suite coverage snapshot

## Contributors

<table>
   <tr>
      <td align="center"><a href="https://github.com/pranavnbapat"><img src="https://avatars.githubusercontent.com/u/7271334?v=4" width="100;" alt="pranavnbapat"/><br /><sub><b>Pranav Bapat</b></sub></a></td>
      <td align="center"><a href="https://github.com/Cloud956"><img src="https://avatars.githubusercontent.com/u/24865274?v=4" width="100;" alt="Cloud956"/><br /><sub><b>Piotr Lewandowski</b></sub></a></td>
      <td align="center"><a href="https://github.com/shashankmc"><img src="https://avatars.githubusercontent.com/u/3445114?v=4" width="100;" alt="shashankmc"/><br /><sub><b>shashankmc</b></sub></a></td>
      <td align="center"><a href="https://github.com/gijsvd"><img src="https://avatars.githubusercontent.com/u/31765316?v=4" width="100;" alt="gijsvd"/><br /><sub><b>gijsvd</b></sub></a></td>
      <td align="center"><a href="https://github.com/venvis"><img src="https://avatars.githubusercontent.com/venvis" width="100;" alt="venvis"/><br /><sub><b>venvis</b></sub></a></td>
      <td align="center"><a href="https://github.com/davidwickerhf"><img src="https://avatars.githubusercontent.com/davidwickerhf" width="100;" alt="davidwickerhf"/><br /><sub><b>davidwickerhf</b></sub></a></td>
   </tr>
</table>

## How to install?

```bash
pip install cellar-extractor
```

## What The Project Does

`cellar-extractor` builds enriched EUR-Lex / CELLAR case-law datasets.

It starts from CELLAR metadata and then enriches:

- citation edges
- summaries and keywords
- full text
- sector-specific metadata
- graph-ready node/edge projections

The extractor is currently centered on:

- **sector 6** case law: CJEU-style material via InfoCuria
- **sector 8** case law: mixed / national-case-law material via CELLAR RDF + item downloads
- **sector 3** legislation (and **sector 0** consolidated versions): full XHTML via the CELLAR REST API content-negotiation endpoint

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
| Sector 3 legislation full text (and sector 0 consolidated) | CELLAR REST `resource/celex/{CELEX}` with `Accept: application/xhtml+xml` |
| Legacy citation comparison only | EUR-Lex SOAP webservice |

## Quick Start

### 1. Fetch Base CELLAR Metadata

```python
import cellar_extractor as cell

df = cell.get_cellar(
    save=False,
    file_format="csv",
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    max_ecli=100,
)
```

Returns a dataframe with base metadata such as CELEX, ECLI, type, dates, and subject-matter-related fields.

You can also save explicitly to a custom path instead of the default `data/` location:

```python
cell.get_cellar(
    save=True,
    file_format="csv",
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    output_path="exports/cellar_january.csv",
)
```

### 2. Fetch The Enriched Dataset

```python
import cellar_extractor as cell

extra_df, fulltext = cell.get_cellar_extra(
    save=False,
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    max_ecli=100,
    threads=4,
)
```

Returns:

- `extra_df`: enriched dataframe
- `fulltext`: list of JSON rows containing extracted text and provenance

You can independently control where the enriched CSV and fulltext JSON are written:

```python
cell.get_cellar_extra(
    save=True,
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    metadata_output_path="exports/cellar_extra.csv",
    fulltext_output_path="exports/cellar_fulltext.json",
    threads=4,
)
```

### 3. Fetch Legislation By CELEX (Sector 3 / Sector 0)

Legislation does not have an ECLI and is not part of `get_cellar(...)`. To fetch a regulation, directive, or consolidated version directly:

```python
import cellar_extractor as cell

gdpr = cell.get_legislation_by_celex_id("32016R0679", language="EN")
print(gdpr["text_source"])     # "CELLAR_REST_XHTML"
print(gdpr["text_format"])     # "xhtml"
print(gdpr["text"][:200])      # plain-text extraction of the XHTML
```

This calls the CELLAR content-negotiation REST endpoint (`https://publications.europa.eu/resource/celex/{CELEX}`) with `Accept: application/xhtml+xml` and returns the same dict shape as the case-law per-CELEX paths (`html`, `text`, `text_language`, `missing_reasons`, etc.). Consolidated CELEXes such as `02002L0058-20091219` are handled the same way.

### 4. Build A Citation Graph

```python
import cellar_extractor as cell

nodes, edges = cell.get_nodes_and_edges_lists(extra_df, only_local=True)
```

`only_local=True` keeps only edges whose target CELEX is also present in `extra_df`.

### 5. Filter By Subject Matter

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
- use `save=True` for long runs
- keep the fulltext JSON files; they are the canonical extracted text output

Example file-based run:

```python
import cellar_extractor as cell

cell.get_cellar_extra(
    save=True,
    sd="2025-01-01",
    ed="2025-01-31T23:59:59",
    max_ecli=5000,
    threads=6,
)
```

By default this writes into `data/`:

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
| `get_cellar(...)` | Fetch base CELLAR metadata (case law only) |
| `get_cellar_extra(...)` | Fetch enriched metadata + full text (case law only) |
| `get_legislation_by_celex_id(celex, language="EN")` | Fetch sector 3 / sector 0 legislation XHTML by CELEX |
| `get_nodes_and_edges_lists(df, only_local=False)` | Build citation graph lists |
| `filter_subject_matter(df, phrase)` | Filter dataframe by subject phrase |
| `FetchOperativePart` | Extract operative part from a single case document |
| `Writing` | Write operative-part outputs to CSV / JSON / TXT |

### Core Modules

#### [`cellar_extractor/cellar.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar.py)

- `get_cellar(ed=None, save_file=<deprecated>, max_ecli=100, sd="2022-05-01", file_format="csv", output_dir="data", output_path=None, return_data=None, save=None)`
- `get_cellar_extra(ed=None, save_file=<deprecated>, max_ecli=100, sd="2022-05-01", threads=10, username="", password="", output_dir="data", metadata_output_path=None, fulltext_output_path=None, save_metadata=None, save_fulltext=None, return_data=None, save=None)`
- `get_nodes_and_edges_lists(df=None, only_local=False)`
- `filter_subject_matter(df=None, phrase=None)`

Notes:

- `username` / `password` are legacy compatibility parameters and no longer change the extraction path
- `save` is the preferred save toggle; `save_file` is kept as a deprecated compatibility alias
- `output_path`, `metadata_output_path`, and `fulltext_output_path` let callers choose exact output locations instead of relying on fixed folders
- when save flags are disabled, the package returns in-memory objects without writing files

#### [`cellar_extractor/citations_adder.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/citations_adder.py)

- `add_citations_separate(data, threads)`: production citation enrichment
- `add_citations_separate_webservice(data, username, password)`: deprecated legacy comparison path
- `add_citations(data, threads)`: older citation replacement helper

#### [`cellar_extractor/fulltext_saving.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/fulltext_saving.py)

- `add_sections(data, threads, output_path=None, json_filepath=None, fulltext_output_path=None)`: enriches summaries, keywords, text metadata, provenance, and missing-data flags

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
| CELLAR REST `https://publications.europa.eu/resource/celex/{CELEX}` (with `Accept: application/xhtml+xml`) | sector 3 legislation and sector 0 consolidated XHTML |
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
RUN_WEBSERVICE_INTEGRATION=1 pytest -q tests/test_webservice_credentials_integration.py tests/test_webservice_redundancy_integration.py
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
