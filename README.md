# Cellar Extractor

`cellar-extractor` is a Python library for downloading and enriching EUR-Lex / CELLAR case-law datasets.

The extractor is now explicitly source-aware:

- sector `6` case law (CJEU / General Court / Civil Service Tribunal style material) is enriched through InfoCuria
- sector `8` case law (mixed / national-case-law-style material in CELLAR) is enriched through CELLAR RDF + item endpoints
- citation edges are enriched through the public CELLAR SPARQL endpoint
- the EUR-Lex SOAP webservice is retained only for legacy validation tests and is deprecated for production extraction

This README is written for two audiences at once:

- new contributors who need a clean mental model of the pipeline
- maintainers who need field-level provenance, test strategy, and current completeness boundaries

## Status

- Python: `>=3.9`
- Main extraction path: credential-free
- EUR-Lex SOAP webservice: deprecated in the extractor pipeline
- Citation graph source of truth: SPARQL
- Sector-8 completeness model: best effort + explicit unavailability flags

## Why The Webservice Was Deprecated

Historically, the project used the EUR-Lex SOAP webservice for citation enrichment. That path is now deprecated in the extractor for two reasons:

1. The extractor only used the SOAP payload for citation relations.
2. The public SPARQL endpoint now provides the same outbound citation information and stronger inbound citation coverage.

In practical terms:

- outbound citations (`citing`) can be reproduced through SPARQL
- inbound citations (`cited_by`) are better represented through SPARQL than through the legacy webservice wrapper
- no other extractor field depends on SOAP

The repository still contains:

- raw SOAP request support in [`cellar_extractor/sparql.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/sparql.py)
- SOAP response parsing helpers in [`cellar_extractor/eurlex_scraping.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/eurlex_scraping.py)
- legacy redundancy tests in [`tests/test_webservice_credentials_integration.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_webservice_credentials_integration.py) and [`tests/test_webservice_redundancy_integration.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_webservice_redundancy_integration.py)

Those pieces now exist to verify redundancy, not to power the production pipeline.

## Source Architecture

### 1. Base Corpus Acquisition

Base metadata starts with the CELLAR SPARQL endpoint:

- ECLIs are discovered through [`cellar_extractor/cellar_queries.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar_queries.py)
- raw metadata is normalized into CSV/JSON through [`cellar_extractor/json_to_csv.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/json_to_csv.py)

Entry point:

- [`cellar_extractor/cellar.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar.py)

Public function:

- `get_cellar(...)`

### 2. Citation Enrichment

Citation enrichment is handled by [`cellar_extractor/citations_adder.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/citations_adder.py).

Current production behavior:

- `add_citations_separate(...)` uses SPARQL
- `add_citations_separate_webservice(...)` is deprecated and retained only for validation
- [`cellar_extractor/cellar_extra_extract.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar_extra_extract.py) always uses the SPARQL path, even if legacy credentials are provided

The resulting dataframe columns are:

- `citing`: semicolon-delimited outbound CELEX edges
- `cited_by`: semicolon-delimited inbound CELEX edges

### 3. Fulltext / Metadata Enrichment

Fulltext and metadata enrichment is handled by [`cellar_extractor/fulltext_saving.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/fulltext_saving.py), which delegates resolution by CELEX sector through [`cellar_extractor/eurlex_scraping.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/eurlex_scraping.py).

Sector dispatch:

- sector `6` -> InfoCuria APIs / document endpoints
- sector `8` -> CELLAR RDF graph + downloadable `item` manifestations
- unknown / unsupported -> legacy fallback behavior where still present

### 4. Graph Projection

Graph generation is handled by [`cellar_extractor/nodes_and_edges.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/nodes_and_edges.py).

Public function:

- `get_nodes_and_edges_lists(df, only_local=False)`

This projects `citing` relations into:

- `nodes`
- `edges` in `SOURCE,TARGET` string form

`only_local=True` keeps only edges whose target also exists in the input dataframe.

## Field-Level Mapping

The extractor is intentionally multi-source. The table below reflects the current production path.

| Output field | Sector 6 source | Sector 8 source | Notes |
| --- | --- | --- | --- |
| base CELLAR metadata columns | CELLAR SPARQL | CELLAR SPARQL | Comes from `get_cellar(...)` |
| `citing` | SPARQL `work_cites_work` | SPARQL `work_cites_work` | Authoritative citation source in this repo |
| `cited_by` | SPARQL reverse `work_cites_work` | SPARQL reverse `work_cites_work` | Stronger than legacy SOAP wrapper |
| fulltext JSON `text` | InfoCuria HTML/blob/document content | CELLAR item content (`html`, `xml`, or `pdf`) | Preferred downstream fulltext field |
| fulltext JSON `text_source` | InfoCuria | CELLAR item | Explicit provenance |
| fulltext JSON `text_language` | InfoCuria document language | manifestation language | Explicit provenance |
| fulltext JSON `text_format` | usually `html` | `html`, `xml`, or `pdf` | Explicit provenance |
| `celex_summary` | InfoCuria metadata, with HTML fallback where available | summary item if present in CELLAR | Empty values must carry `missing_reasons` |
| `celex_keywords` | InfoCuria metadata | CELLAR subject-matter graph / summary item | Depends on upstream availability |
| `celex_directory_codes` | InfoCuria metadata | best effort from CELLAR subject matter | Sector 8 may be sparse |
| `celex_eurovoc` | InfoCuria metadata | best effort from CELLAR subject matter | Sector 8 may be sparse |
| `advocate_general` | InfoCuria metadata | usually unavailable upstream | Explicitly left empty when not provided upstream |
| `judge_rapporteur` | InfoCuria metadata | usually unavailable upstream | Explicitly left empty when not provided upstream |
| `affecting_ids` / `affecting_strings` | InfoCuria metadata | usually unavailable upstream | Sector 8 remains limited |
| `citations_extra_info` | InfoCuria metadata | usually unavailable upstream | Separate from citation-edge graph |
| `fulltext_source` | InfoCuria | CELLAR item | CSV provenance column |
| `summary_source` | InfoCuria / CELLAR summary item | CELLAR summary item | CSV provenance column |
| `missing_reasons` | generated by extractor | generated by extractor | Prevents false confidence |

## Completeness Model

This repository does not silently treat empty values as success.

### Citation Completeness

Current expectation:

- every record returned by `get_cellar_extra(...)` receives `citing` and `cited_by`
- if a document has no relations, the columns are present and empty
- citation counts are verified against independent live SPARQL count queries in integration tests

### Fulltext / Summary Completeness

Current expectation:

- if fulltext exists upstream and our resolver can access it, it is written to fulltext JSON output
- if summary exists upstream and our resolver can access it, it is written to the dataframe
- if either is missing, `missing_reasons` must say so

Current standardized flags include:

- `FULLTEXT_UNAVAILABLE_UPSTREAM`
- `SUMMARY_UNAVAILABLE_UPSTREAM`
- `UNAVAILABLE_UPSTREAM`

### Sector-8 Completeness

Sector `8` is best effort by design.

What this means:

- the resolver no longer depends on blocked EUR-Lex HTML pages
- it resolves available manifestations through the CELLAR RDF graph
- it parses supported formats from downloadable `item` endpoints
- it does not invent metadata that upstream does not expose

So sector `8` is substantially better than the old behavior, but still bounded by upstream CELLAR availability.

## Public API

### `get_cellar(...)`

Returns a base CELLAR dataset as CSV-like dataframe or JSON-like dictionary.

Parameters:

- `max_ecli: int = 100`
- `sd: str = "2022-05-01"`: start date
- `ed: Optional[str] = current time`
- `save_file: str = "y"`: `"y"` writes files, `"n"` returns in memory
- `file_format: str = "csv"`: `"csv"` or `"json"`

### `get_cellar_extra(...)`

Runs the full enrichment path.

Parameters:

- `max_ecli: int = 100`
- `sd: str = "2022-05-01"`
- `ed: Optional[str] = current time`
- `save_file: str = "y"`
- `threads: int = 10`
- `username: str = ""`
- `password: str = ""`

Important behavior:

- `username` and `password` are now legacy compatibility parameters
- passing them does not change extraction behavior
- citations are always enriched through SPARQL

Returns:

- in-memory mode: `(dataframe, fulltext_json_rows)`
- file mode: writes `<name>.csv` and `<name>_fulltext.json`

### `get_nodes_and_edges_lists(df, only_local=False)`

Builds a citation graph from the enriched dataframe.

Requirements:

- input dataframe must already contain `citing`

Returns:

- `nodes`
- `edges`

### `filter_subject_matter(df, phrase)`

Simple dataframe filter over `LEGAL RESOURCE IS ABOUT SUBJECT MATTER`.

## Quick Start

Install:

```bash
pip install cellar-extractor
```

In-memory usage:

```python
import cellar_extractor as cell

df = cell.get_cellar(save_file="n", file_format="csv", sd="2025-01-01", max_ecli=100)
extra_df, fulltext = cell.get_cellar_extra(
    save_file="n",
    sd="2025-01-01",
    max_ecli=100,
    threads=4,
)
nodes, edges = cell.get_nodes_and_edges_lists(extra_df, only_local=True)
```

File-writing usage:

```python
import cellar_extractor as cell

cell.get_cellar(save_file="y", max_ecli=200, sd="2025-01-01", file_format="csv")
cell.get_cellar_extra(save_file="y", max_ecli=100, sd="2025-01-01", threads=4)
```

## Output Shape

`get_cellar_extra(...)` produces two outputs:

1. An enriched dataframe / CSV
2. A fulltext JSON list

The dataframe now includes, in addition to base CELLAR metadata:

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

Each fulltext JSON row includes:

- `celex`
- `ecli`
- `text`
- `text_source`
- `text_language`
- `text_format`
- `missing_reasons`

## Test Strategy

The test suite is split into local unit tests and live integration tests.

### Fast Local Tests

These should pass without network access:

- [`tests/test_citations_adder_local.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_citations_adder_local.py)
- [`tests/test_nodes_and_edges_local.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_nodes_and_edges_local.py)
- [`tests/test_extra_cellar_local.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_extra_cellar_local.py)
- [`tests/test_fulltext_saving_local.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_fulltext_saving_local.py)
- [`tests/test_infocuria_adapter.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_infocuria_adapter.py)
- [`tests/test_sector8_adapter.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_sector8_adapter.py)
- [`tests/test_retry_behavior.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_retry_behavior.py)

Run:

```bash
pytest -q
```

### Live Integration Flags

Live suites are opt-in.

- `RUN_INFOCURIA_INTEGRATION=1`: sector-6 live tests
- `RUN_SECTOR8_INTEGRATION=1`: sector-8 live tests
- `RUN_CITATION_INTEGRATION=1`: live citation-count and graph-consistency tests

Examples:

```bash
RUN_INFOCURIA_INTEGRATION=1 pytest -q tests/test_infocuria_integration.py
RUN_SECTOR8_INTEGRATION=1 pytest -q tests/test_sector8_integration.py
RUN_CITATION_INTEGRATION=1 pytest -q tests/test_citation_graph_integration.py
```

### Legacy Webservice Validation Tests

These tests are intentionally separate from the production path:

- [`tests/test_webservice_credentials_integration.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_webservice_credentials_integration.py)
- [`tests/test_webservice_redundancy_integration.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/tests/test_webservice_redundancy_integration.py)

They exist to answer one question:

- does SOAP provide anything the extractor still needs?

Current answer in this repo:

- no, not for production extraction

Credentials are loaded from `.env`:

```env
EURLEX_WEBSERVICE_USERNAME=
EURLEX_WEBSERVICE_PASSWORD=
```

These are only needed for legacy redundancy checks. They are not needed to run `get_cellar_extra(...)`.

Run serially:

```bash
pytest -q tests/test_webservice_credentials_integration.py tests/test_webservice_redundancy_integration.py
```

## Citation Graph Guarantees

The repository now tests citation behavior at three levels:

1. Local aggregation logic
   - rows with only inbound or only outbound relations are preserved
   - duplicates are collapsed
   - empty rows remain explicit
2. Graph projection logic
   - `get_edges_list(...)` faithfully projects `citing`
   - `only_local=True` removes external targets only
3. Live endpoint consistency
   - outbound edge counts match raw SPARQL counts
   - inbound edge counts match raw SPARQL counts
   - local reciprocal edges check out across the sample network

## Repository Layout

Core package:

- [`cellar_extractor/cellar.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar.py): public API
- [`cellar_extractor/cellar_queries.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar_queries.py): base CELLAR metadata queries
- [`cellar_extractor/cellar_extra_extract.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/cellar_extra_extract.py): enrichment orchestration
- [`cellar_extractor/citations_adder.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/citations_adder.py): citation enrichment
- [`cellar_extractor/eurlex_scraping.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/eurlex_scraping.py): InfoCuria / CELLAR source adapters
- [`cellar_extractor/fulltext_saving.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/fulltext_saving.py): dataframe/fulltext assembly
- [`cellar_extractor/nodes_and_edges.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/nodes_and_edges.py): graph projection
- [`cellar_extractor/sparql.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/sparql.py): SPARQL and legacy SOAP network helpers

Tests:

- `tests/test_*_local.py`: local deterministic tests
- `tests/test_*_integration.py`: live endpoint checks

## Troubleshooting

### `missing_reasons` is populated

This is expected whenever upstream does not expose the requested fulltext or summary. Empty values without a corresponding missing-reason code are considered a bug.

### SOAP credentials fail

That does not block the extractor. SOAP is no longer required for production use.

### Live citation tests fail but unit tests pass

That usually means either:

- a transient SPARQL endpoint issue
- a schema / namespace change upstream
- a behavior change in the live graph

The first check should be [`cellar_extractor/sparql.py`](/Users/davidwickerhf/Projects/work/maastricht/cellar-extractor/cellar_extractor/sparql.py), especially prefixes and relation direction.

### Sector-8 fields are sparse

This is usually upstream-limited, not parser-limited. Check:

- whether a work URI resolves
- whether a summary item exists
- whether any downloadable manifestation exists in the requested language
- `missing_reasons`

## Contributors

This project is maintained in the Maastricht Law & Tech Lab ecosystem and has contributions from multiple collaborators over time.

## License

[Apache License 2.0](https://opensource.org/licenses/Apache-2.0)
