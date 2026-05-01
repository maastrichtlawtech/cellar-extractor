# CJEU / CELLAR — Output Field Catalogue

This is the authoritative reference for every field that `cellar-extractor` may emit per document. Names are **lowercase snake_case**, stable across upstream label drift, and identical between the per-row JSON dump and the flattened CSV.

The Python source of truth is [`cellar_extractor/schema.py`](cellar_extractor/schema.py), specifically `FIELD_MANIFEST`. The same data is available programmatically via:

```python
from cellar_extractor import schema
schema.describe()                  # full manifest (list of dicts)
schema.describe(canonical_only=True)
schema.CANONICAL_COLUMNS           # the contracted column set
schema.CDM_PREDICATE_TO_CANONICAL  # CDM URI local part -> canonical name
```

---

## 0. The contract

Every per-document row carries exactly these properties:

1. **All canonical fields** (currently **58**, listed in §A–J below) appear as keys in every row, populated with the upstream value or `null` when the upstream did not return one. Same shape across all rows, all sectors.
2. **Discoverable fields** — CDM predicates the package surfaces opportunistically when the upstream returns them, listed in §K. They appear under a deterministic snake_case fallback name (URI local part with `-`/`.`/`/` folded to `_` and camelCase split). They are **not** part of the canonical contract: they may or may not be present on a given row.
3. **Denied fields** — internal RDF plumbing the package deliberately drops, listed in §L.

No other CDM predicate is silently lost: anything outside the denylist either has a canonical name (§A–J) or is exposed under its fallback name (§K).

### Conventions used in the tables below

- **Type** — observed value type after flattening: `string`, `date` (`YYYY-MM-DD`), `datetime` (ISO 8601), `integer`, `boolean` (`0`/`1`), `url`, `xml`.
- **Cardinality** — `single` (at most one value) or `multi` (`;`-joined list of values inside a single string cell).
- **Sector** — which sectors actually populate the field: `any`, `case_law` (sectors 6 + 8), `legislation` (sectors 3 + 0), `sector_8`, `sector_3`. `any` does not mean "always present" — it means populated for both case law and legislation when available.
- **Source** —
  - **CDM** = CELLAR SPARQL endpoint (`https://publications.europa.eu/webapi/rdf/sparql`), CDM ontology under `http://publications.europa.eu/ontology/cdm#`. Source URI is the predicate URI local part.
  - **InfoCuria** = `https://infocuriaws.curia.europa.eu/elastic-connector/...` JSON, key from the procedure / document hit content.
  - **CELLAR REST** = `https://publications.europa.eu/resource/celex/{CELEX}` content-negotiated XHTML.
  - **enrichment** = computed by `add_sections` / `add_citations_separate` after fetching upstream.

---

## A. Core identifiers

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`celex`** | string | single | any | CDM `resource_legal_id_celex` | CELEX identifier — sector + year + type-letter + number, with optional consolidation suffix for sector 0. | `62024CJ0072` |
| **`ecli`** | string | single | case_law | CDM `case-law_ecli` | European Case Law Identifier. `null` for legislation. | `ECLI:EU:C:2026:51` |
| `sector` | string | single | any | CDM `resource_legal_id_sector` | CELEX sector. `0` consolidated, `3` secondary legislation, `6` CJEU case law, `8` national case law. | `6` |
| `resource_legal_type` | string | single | any | CDM `resource_legal_type` | CELEX type-letter (`CJ`, `CO`, `CC`, `R`, `L`, `D`). | `CO` |
| `year_of_resource` | integer | single | any | CDM `resource_legal_year` | Year embedded in the CELEX. | `2023` |
| `natural_number_celex` | integer | single | any | CDM `resource_legal_number_natural_celex` | Numeric tail of the CELEX. | `800` |
| `local_identifier` | string | single | sector_8 | CDM `resource_legal_id_local` | Court-issued local identifier (national case numbers etc.). | `20 Cdo 1073/2025` |
| `alternate_identifiers` | string | multi | any | CDM `work_id_document` | All alternate identifier schemes for this work. | `celex:62023CO0800;ecli:ECLI:EU:C:2025:1` |
| `work_version` | string | single | any | CDM `work_version` | Version label. | `definitive` / `rectified/1` |

---

## B. Document type

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`resource_type`** | string | multi | any | CDM `work_has_resource-type` | Document type label (skos:prefLabel). Multiple values when one work has more than one published manifestation. | `Order` / `Judgment;Abstract` |

---

## C. Dates

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`date_publication`** | date | single | any | CDM `work_date_document` | Document delivery / publication date. | `2025-01-07` |
| `date_of_request` | date | single | case_law | CDM `resource_legal_date_request_opinion` | Date of request for an Opinion / preliminary ruling lodgement. | `2023-12-28` |
| `date_of_creation` | datetime | multi | any | CDM `lastModificationDate` | Most recent CMR last-modified timestamp; multi-valued when CELLAR re-indexes the work. | `2026-04-17T20:56:41.157+02:00` |
| `creation_date` | datetime | single | any | CDM `creationDate` | Original CMR record-creation timestamp. | `2025-01-15T07:49:16.490+01:00` |
| `work_date_creation_legacy` | date | single | any | CDM `work_date_creation_legacy` | Legacy creation date carried from before the modern CMR. | `2025-01-15` |
| `date_signature` | date | single | legislation | CDM `resource_legal_date_signature` | Date the act was signed. | `2016-04-27` |
| `date_end_of_validity` | date | single | legislation | CDM `resource_legal_date_end-of-validity` | End-of-validity (`9999-12-31` = act still active). | `9999-12-31` |

---

## D. Court / parties / agents

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`delivered_by_court_formation`** | string | single | case_law | CDM `case-law_delivered_by_court-formation` | Court formation that delivered the judgment. | `Tenth Chamber` |
| **`commented_by_agent`** | string | multi | case_law | CDM `case-law_commented_by_agent` | Member states / EU institutions that submitted observations. | `Belgium;EU institutions and bodies;European Commission` |
| **`advocate_general`** | string | single | case_law | InfoCuria `advocateML` (resolved EN) | Surname (with optional initial) of the Advocate General. | `Campos Sánchez-Bordona` |
| **`judge_rapporteur`** | string | single | case_law | InfoCuria `reportingJudgeML` (resolved EN) | Surname of the Judge Rapporteur. | `Smulders` |

---

## E. Procedure

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`judicial_procedure_type`** | string | single | case_law | CDM `case-law_has_procjur` | Broad procedural class. | `Reference for a preliminary ruling` |
| **`type_procedure`** | string | single | case_law | CDM `case-law_has_type_procedure_concept_type_procedure` | Refined procedural label, often with state qualifier. | `Reference for a preliminary ruling - inadmissible` |
| **`language_procedure`** | string | single | case_law | CDM `case-law_uses_procedure_language` | Procedural language. | `Dutch` |
| **`origin_country`** | string | multi | case_law | CDM `case-law_originates_in_country` | Country of origin (referring court / action-respondent). Joined cases can have multiple. | `Belgium` |
| **`origin_country_or_role_qualifier`** | string | multi | case_law | CDM `case-law_originates_in_country_role-qualifier` | Country of origin enriched with role qualifier. | `Belgium` |
| **`conclusions`** | url | single | case_law | CDM `case-law_has_conclusions_opinion_advocate-general` | CELLAR URI of the AG Opinion linked to this case. | `http://publications.europa.eu/resource/cellar/8e01d479-…` |
| **`legal_resource`** | url | multi | case_law | CDM `case-law_interpretes_resource_legal` | Legal resource(s) the case interprets. | `http://publications.europa.eu/resource/cellar/4fd758c9-…` |

---

## F. Subject matter / classification

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`subject_matter`** | string | multi | any | CDM `resource_legal_is_about_subject-matter` | Top-level subject matter taxonomy. | `Free movement of goods;Customs Union and Common Customs Tariff` |
| **`directory_codes`** | string | multi | case_law | InfoCuria `matCode` | EUR-Lex case-law directory codes. | `DFON;LCMA;PRIN` |
| **`eurovoc`** | string | multi | case_law | InfoCuria `matCodeML` (resolved EN) | EuroVoc concept labels. | `Fundamental rights;Free movement of goods` |
| **`keywords`** | string | multi | case_law | InfoCuria `matCodeML` | Backwards-compat surface form of `eurovoc` (same content on most rows). | `Fundamental rights;Free movement of goods` |
| **`based_on_treaty`** | string | multi | legislation | CDM `resource_legal_based_on_concept_treaty` | Treaty basis. | `Treaty on the Functioning of the European Union (consolidated version 2012)` |

---

## G. Legislation-specific

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`eli`** | url | single | legislation | CDM `resource_legal_eli` | European Legislation Identifier — canonical URL of the act. | `http://data.europa.eu/eli/reg/2016/679/oj` |
| **`in_force`** | boolean | single | legislation | CDM `resource_legal_in-force` | Boolean flag: is the act still in force? | `1` |
| `is_eea_relevant` | boolean | single | legislation | CDM `resource_legal_eea` | Boolean flag: is the act EEA-relevant? | `1` |
| `is_codified_version` | boolean | single | legislation | CDM `resource_legal_codified_version` | Boolean flag: is this a codified version? | `0` |
| `repertoire` | string | single | legislation | CDM `resource_legal_repertoire` | Repertoire-of-legislation-in-force flag. | `REP` |
| `oj_reference` | string | single | legislation | CDM `resource_legal_reference_oj-act` | Compact OJ reference. | `2024/1689` |
| `oj_domain_reference` | string | single | legislation | CDM `resource_legal_domain_reference_oj-act` | OJ act domain. | `EU` |
| `manuscript_ref` | string | single | legislation | CDM `resource_legal_manuscript_ref` | Manuscript reference for the OJ submission. | `PE 17 2016 INIT` |
| `responsibility_agent` | string | multi | legislation | CDM `resource_legal_responsibility_of_agent` | Responsible Commission DG / agent. | `Eurostat;Directorate-General for Justice and Consumers` |
| `internal_status_code` | string | single | legislation | CDM `resource_legal_comment_internal` | Internal CMR status code. | `MAN2` |

---

## H. National-judgement passthrough (sectors 6 + 8)

| Canonical field | Type | Card. | Sector | Source | Description |
|---|---|---|---|---|---|
| **`national_judgement`** | xml | single | case_law | CDM `case-law_national-judgement` | Raw `<national_judgement>` block — referring national court, decision date, case ids. |
| `references_journals` | string | multi | case_law | CDM `case-law_article_journal_related` | References to journal articles indexing the case. |

---

## I. Citation graph & affecting relations

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`citing`** | string | multi | any | enrichment via SPARQL `add_citations_separate` | CELEX ids of works this document cites (out-edges). | `32012Q0929(01);62015CO0328` |
| **`cited_by`** | string | multi | any | enrichment via SPARQL `add_citations_separate` | CELEX ids of works that cite this document (in-edges). | `62025CO0114` |
| **`affecting_ids`** | string | multi | case_law | InfoCuria `joinAffairs` / `pourvoiAffIds` / `transfertAffIds` / `reExamenAffIds` | Clean published case numbers of affecting cases. | `C-73/24` |
| **`affecting_string`** | string | multi | case_law | as above, prefixed with relation kind | Affecting cases prefixed with relation kind. Kinds: `joined`, `appeal_against`, `appealed_in`, `re-examines`, `re-examined_in`, `transfers`, `transferred_from`. | `joined: C-73/24` |
| **`citations_extra_info`** | string | single | case_law | InfoCuria `parties` + `procedureResultTypeML` | Composite of party names + procedure result type. | `DRINKS 52;Reference for a preliminary ruling: dismissal on grounds of inadmissibility` |

---

## J. Texts and provenance

| Canonical field | Type | Card. | Sector | Source | Description | Example |
|---|---|---|---|---|---|---|
| **`summary`** | string | single | case_law | InfoCuria document `contentML` | Plain-text summary of the case. Sector 6 only. | `Summary C-800/23 …` |
| `text_source` | string | single | any | enrichment | Provenance of the full text. | `INFOCURIA_BLOB_HTML` / `CELLAR_ITEM` / `CELLAR_REST_XHTML` / `EXTRACTOR_FALLBACK_TEXT` / `null` |
| `text_format` | string | single | any | enrichment | Markup format of the full text. | `html` / `xhtml` / `pdf` / `xml` |
| `text_language` | string | single | any | enrichment | ISO-639-1 language code. | `EN` / `DE` |
| `summary_source` | string | single | case_law | enrichment | Provenance of the summary. | `INFOCURIA_DOCUMENT_CONTENT` / `INFOCURIA_AFF_OBJECT` / `CELLAR_SUMMARY_ITEM` |
| `summary_language` | string | single | case_law | enrichment | Language of the summary text. | `EN` |
| `fulltext_source` | string | single | any | enrichment | Mirror of `text_source` for backwards compatibility. | `INFOCURIA_BLOB_HTML` |
| `missing_reasons` | string | multi | any | enrichment | `;`-joined flags marking absent upstream content. Empty when retrieval was complete. | `FULLTEXT_UNAVAILABLE_UPSTREAM;SUMMARY_UNAVAILABLE_UPSTREAM` |

The full text itself lives in the **fulltext JSON** sidecar (`<output>_fulltext.json`), not in the metadata CSV. Each entry has the shape:

```json
{
  "celex": "62024CJ0072",
  "ecli": "ECLI:EU:C:2026:51",
  "text": "<plain text…>",
  "text_source": "INFOCURIA_BLOB_HTML",
  "text_language": "EN",
  "text_format": "html",
  "missing_reasons": ""
}
```

---

## K. Discoverable fields

CDM predicates the package surfaces opportunistically — they appear on a given row only when the upstream returned a value. Names are derived from the URI local part: hyphens / dots / camelCase folded to underscores. Surveyed prevalence is across 200 case-law ECLIs (2023–2024) + 15 hand-picked legislation CELEXes.

| Discoverable field | Type | Card. | CL % | LEG % | Source URI local part | Description |
|---|---|---|---|---|---|---|
| `case_law_is_about_case_law_subject_matter` | string | multi | 61 | — | `case-law_is-about_case-law-subject-matter` | Case-law-specific subject taxonomy, distinct from `subject_matter`. |
| `case_law_is_about_concept_new_case_law` | string | multi | 48 | — | `case-law_is_about_concept_new_case-law` | Newer case-law concept axis. |
| `case_law_published_in_erecueil` | string | single | 63 | — | `case-law_published_in_erecueil` | eRecueil reference flag. |
| `case_law_delivered_by_advocate_general` | url | single | usually | — | `case-law_delivered_by_advocate-general` | CELLAR resource URI of the AG (raw, unresolved — resolved name is in canonical `advocate_general`). |
| `case_law_delivered_by_judge` | url | single | usually | — | `case-law_delivered_by_judge` | CELLAR resource URI of the judge (raw). |
| `case_law_delivered_by_court_national` | url | single | sector_8 | — | `case-law_delivered_by_court_national` | CELLAR resource URI of the national court. |
| `case_law_defended_by_agent` | string | multi | 14 | — | `case-law_defended_by_agent` | Defendant agent(s). |
| `case_law_requested_by_agent` | string | multi | 14 | — | `case-law_requested_by_agent` | Requesting / applicant agent(s). |
| `case_law_joins_case_court` | url | multi | 5 | — | `case-law_joins_case_court` | Joined-case URI references. |
| `case_law_amends_resource_legal` | url | multi | rare | — | `case-law_amends_resource_legal` | Legal resource amended by the case. |
| `case_law_confirms_resource_legal` | url | multi | rare | — | `case-law_confirms_resource_legal` | Legal resource confirmed. |
| `case_law_declares_void_resource_legal` | url | multi | rare | — | `case-law_declares_void_resource_legal` | Legal resource declared void. |
| `case_law_referred_to_for_preliminary_ruling_case_law` | url | single | 2 | — | `case-law_referred_to_for_preliminary_ruling_case-law` | Other case-law referred to in a preliminary ruling. |
| `case_law_states_failure_concerning_resource_legal` | url | multi | 1 | — | `case-law_states_failure_concerning_resource_legal` | Failure-to-fulfil ruling target. |
| `case_law_national_act_reference_european` | string | multi | 34 | — | `case-law_national_act_reference_european` | Free-text references to European acts. |
| `case_law_national_act_reference_national` | xml | single | 34 | — | `case-law_national_act_reference_national` | XML-wrapped references to national legislation. |
| `case_law_national_based_on_resource_legal` | url | multi | 38 | — | `case-law_national_based_on_resource_legal` | EU instrument the national judgment relies on. |
| `case_law_national_parties` | xml | single | 9 | — | `case-law_national_parties` | XML-wrapped party names for sector 8 cases. |
| `case_law_national_reference_publication` | xml | single | 6 | — | `case-law_national_reference_publication` | XML-wrapped publication reference for sector 8 cases. |
| `opinion_advocate_general_joined_to_case_court` | url | multi | 12 | — | `opinion_advocate-general_joined_to_case_court` | Reverse link from an Opinion document back to its case. |
| `summary_summarizes_work` | url | single | 50 | — | `summary_summarizes_work` | When the document is a SUMMARY of another work, points at that work. |
| `summary_case_law_id_celex` | string | single | 50 | — | `summary_case-law_id_celex` | Alternate case-law identifier reference. |
| `work_cites_work` | url | multi | 59 | 100 | `work_cites_work` | Raw CELLAR-resource URIs of cited works (see canonical `citing` for CELEX-resolved form). |
| `work_created_by_agent` | string | multi | 100 | 100 | `work_created_by_agent` | Authoring agents (`Court of Justice`, `European Parliament`, …). |
| `work_part_of_dossier` | url | single | 64 | 47 | `work_part_of_dossier` | Dossier the work belongs to (groups Opinion + Judgment + Order of one case). |
| `work_part_of_event` | url | single | 64 | — | `work_part_of_event` | CELLAR event grouping. |
| `work_part_of_event_legal` | url | single | — | 47 | `work_part_of_event_legal` | Legislative-event grouping. |
| `work_is_member_of_complex_work` | url | single | 49 | — | `work_is_member_of_complex_work` | Parent complex-work URI. |
| `work_is_another_publication_of_work` | url | multi | — | 73 | `work_is_another_publication_of_work` | Other publications of the same work. |
| `work_is_logical_successor_of_work` | url | single | rare | — | `work_is_logical_successor_of_work` | Logical successor link. |
| `work_title` | string | single | 38 | 40 | `work_title` | Free-text title (mostly populated for sector 8 + sector 3). |
| `work_table_of_contents` | xml | single | — | rare | `work_table-of-contents` | Embedded `<table-of-contents>` for legislation. |
| `work_embargo` | datetime | single | — | rare | `work_embargo` | Embargo timestamp. |
| `work_id_obsolete_notice` | string | single | — | rare | `work_id_obsolete_notice` | Obsolete CELLAR-internal id. |
| `work_part_of_collection_document` | string | multi | — | rare | `work_part_of_collection_document` | Document collection identifier. |
| `work_date_creation` | date | single | — | rare | `work_date_creation` | Distinct from `creation_date` / `work_date_creation_legacy`. |
| `work_datetime_transmission` | datetime | multi | 49 | — | `work_datetime_transmission` | Transmission timestamp distinct from `datetime_negotiation`. |
| `datetime_negotiation` | url | single | 63 | — | `datetime_negotiation` | Marker URI used by CELLAR's negotiation pipeline. |
| `date_creation_legacy` | date | multi | 64 | 47 | `date_creation_legacy` | Legacy creation date (variant from `work_date_creation_legacy`). |
| `resource_legal_uses_originally_language` | string | multi | 94 | 13 | `resource_legal_uses_originally_language` | Language the work was originally in. |
| `resource_legal_number_natural` | integer | single | — | 100 | `resource_legal_number_natural` | Natural number variant. |
| `resource_legal_number_sequence_celex` | integer | single | 32 | — | `resource_legal_number_sequence_celex` | CELEX sequence number. |
| `resource_legal_adopts_resource_legal` | url | single | — | 100 | `resource_legal_adopts_resource_legal` | What was adopted. |
| `resource_legal_amends_resource_legal` | url | multi | — | 67 | `resource_legal_amends_resource_legal` | What this act amends. |
| `resource_legal_based_on_resource_legal` | url | multi | — | 100 | `resource_legal_based_on_resource_legal` | Legal-basis URIs. |
| `resource_legal_repeals_resource_legal` | url | multi | — | 47 | `resource_legal_repeals_resource_legal` | Acts explicitly repealed. |
| `resource_legal_implicitly_repeals_resource_legal` | url | multi | — | 33 | `resource_legal_implicitly_repeals_resource_legal` | Acts implicitly repealed. |
| `resource_legal_corrects_resource_legal` | url | multi | rare | — | `resource_legal_corrects_resource_legal` | Acts corrected (corrigenda). |
| `resource_legal_does_repeal_of_resource_legal` | url | single | — | 7 | `resource_legal_does_repeal_of_resource_legal` | Performs-repeal-of variant. |
| `resource_legal_does_deletion_of_resource_legal` | url | multi | — | 7 | `resource_legal_does_deletion_of_resource_legal` | Performs-deletion-of variant. |
| `resource_legal_incorporates_resource_legal` | url | single | rare | — | `resource_legal_incorporates_resource_legal` | Acts incorporated. |
| `resource_legal_published_in_official_journal` | url | single | — | 60 | `resource_legal_published_in_official-journal` | OJ publication URI. |
| `resource_legal_published_in_special_official_journal` | url | multi | — | 13 | `resource_legal_published_in_special-official-journal` | Special-OJ publication URIs. |
| `resource_legal_produced_by_dossier` | url | single | — | 33 | `resource_legal_produced_by_dossier` | Dossier that produced the act. |
| `resource_legal_addresses_institution` | string | single | — | 33 | `resource_legal_addresses_institution` | Addressee (e.g. The Member States). |
| `resource_legal_date_entry_into_force` | date | multi | — | 100 | `resource_legal_date_entry-into-force` | Entry-into-force date(s). |
| `resource_legal_date_deadline` | date | multi | — | 80 | `resource_legal_date_deadline` | Implementation deadline(s). |
| `resource_legal_information_miscellaneous` | string | multi | — | 67 | `resource_legal_information_miscellaneous` | Free-text + URI miscellany. |
| `resource_legal_demed_reference` | string | single | — | 40 | `resource_legal_demed_reference` | Internal numeric ID. |
| `resource_legal_position_eesc` | string | single | — | rare | `resource_legal_position_eesc` | EESC position. |
| `resource_legal_signatory_function` | string | single | — | 13 | `resource_legal_signatory_function` | Signatory function (President, etc.). |
| `resource_legal_signatory_function2` | string | single | — | 27 | `resource_legal_signatory_function2` | Second signatory function. |
| `resource_legal_signatory_name` | string | single | — | 40 | `resource_legal_signatory_name` | Signatory name. |
| `resource_legal_signatory_name2` | string | single | — | 40 | `resource_legal_signatory_name2` | Second signatory name. |
| `resource_legal_service_responsible` | string | single | — | rare | `resource_legal_service_responsible` | Internal service code. |
| `resource_legal_sequence` | integer | single | — | 40 | `resource_legal_sequence` | Sequence number of the legal resource. |
| `act_consolidated_based_on_resource_legal` | url | single | — | sector_0 | `act_consolidated_based_on_resource_legal` | Consolidated-act basis. |
| `act_consolidated_consolidates_resource_legal` | url | multi | — | sector_0 | `act_consolidated_consolidates_resource_legal` | Acts consolidated. |
| `act_consolidated_date` | date | single | — | sector_0 | `act_consolidated_date` | Consolidation date. |
| `act_consolidated_layer` | string | single | — | sector_0 | `act_consolidated_layer` | Consolidation layer. |
| `act_consolidated_number` | integer | single | — | sector_0 | `act_consolidated_number` | Consolidation number. |
| `legislation_secondary_modifies_legislation_secondary` | url | multi | — | rare | `legislation_secondary_modifies_legislation_secondary` | Cross-reference between secondary acts. |
| `directive_date_transposition` | date | multi | — | 40 | `directive_date_transposition` | Directive transposition deadline. |
| `directive_service_associated` | string | multi | — | rare | `directive_service_associated` | Directive-specific service codes. |
| `official_journal_act_year` | integer | single | — | 40 | `official-journal-act_year` | OJ year. |
| `official_journal_act_number` | integer | single | — | 40 | `official-journal-act_number` | OJ number. |
| `official_journal_act_section_oj` | string | single | — | 40 | `official-journal-act_section_oj` | OJ section. |
| `official_journal_act_subsection_oj` | string | single | — | 40 | `official-journal-act_subsection_oj` | OJ subsection. |
| `official_journal_act_subsubsection_oj` | string | single | — | 40 | `official-journal-act_subsubsection_oj` | OJ sub-subsection. |
| `official_journal_act_part_of_collection_document` | string | single | — | 40 | `official-journal-act_part_of_collection_document` | OJ collection (`Official Journal L series` / `C series`). |
| `official_journal_act_date_publication` | date | single | — | 40 | `official-journal-act_date_publication` | OJ publication date. |
| `official_journal_act_durability` | string | single | — | 40 | `official-journal-act_durability` | OJ durability flag. |

This list is **the union of CDM predicates the upstream has been observed to return** for at least one document in the survey. Future predicates added by the CELLAR ontology will appear here automatically (under their URI-derived fallback name) without any code change to the package.

---

## L. Denied predicates

These are dropped at the boundary in [`schema.py:CDM_PREDICATE_DENYLIST`](cellar_extractor/schema.py) — internal CELLAR plumbing with no analytical value.

| Predicate | Reason |
|---|---|
| `do_not_index` | Internal CELLAR indexing flag. |
| `memberList` | RDF list-plumbing predicate (members of an `rdf:List`). |

---

## M. Sectors covered

| Sector | Content | Discovery path | Per-doc fetch path |
|--------|---------|----------------|---------------------|
| `0` | Consolidated legislation (e.g. `02002L0058-20091219`) | none yet — fetch by CELEX | `get_legislation_by_celex_id` → CELLAR REST XHTML + CDM SPARQL |
| `3` | Secondary legislation (Regulations, Directives, Decisions) | none yet — fetch by CELEX | `get_legislation_by_celex_id` → CELLAR REST XHTML + CDM SPARQL |
| `6` | CJEU case law | `get_all_eclis(...)` (ECLI-keyed CDM SPARQL) | `get_cellar_extra(...)` → CDM SPARQL + InfoCuria + citation SPARQL |
| `8` | National case law | `get_all_eclis(...)` (ECLI-keyed CDM SPARQL) | `get_cellar_extra(...)` → CDM SPARQL + CELLAR `item` manifestations + citation SPARQL |

---

## N. Sources

- CELLAR SPARQL endpoint: <https://publications.europa.eu/webapi/rdf/sparql>
- CDM ontology base: <http://publications.europa.eu/ontology/cdm>
- InfoCuria search API: `https://infocuriaws.curia.europa.eu/elastic-connector/...` (undocumented; observed live).
- CELLAR REST shortcut: <https://publications.europa.eu/resource/celex/{CELEX}>
- Field-catalogue style template: [`data-mapping/source/echr/FIELDS.md`](../data-mapping/source/echr/FIELDS.md).
- Survey baseline: 200 case-law ECLIs (2023-01-01 → 2024-12-31) + 15 sector-3 CELEXes spanning Regulations / Directives / Decisions / repealed / active. April 2026.
