"""
Canonical schema for the CJEU/CELLAR extractor.

This module is the single source of truth for the package's output structure.
``FIELD_MANIFEST`` lists every metadata field the package may emit, with its
upstream source, type, cardinality, sector affinity, and description.

Conventions (also used in echr-extractor and rechtspraak):

- Lowercase snake_case field names.
- Stable across upstream label drift — keyed on the CDM predicate URI local
  part (stable) rather than ``rdfs:label`` (which can drift).
- Missing values are represented as ``None`` / ``null`` / empty CSV cell.
  The schema is the same shape across every row.
- Multi-valued fields collapse to ``;``-joined strings in the per-row output;
  downstream consumers split on ``;`` (use a satellite table when querying).

Three classes of fields:

1. **Canonical fields** — guaranteed to appear as a column in every row, even
   when ``None``. Defined in ``FIELD_MANIFEST`` with ``canonical=True``.
2. **Discoverable fields** — CDM predicates that don't have a canonical entry
   but that the package still surfaces when the upstream returns them, under a
   deterministic snake_case fallback name derived from the URI local part.
   They appear in the row dict only when populated.
3. **Denied fields** — internal RDF plumbing that carries no analytical value.
   Listed in ``CDM_PREDICATE_DENYLIST`` and never reach the output.
"""

from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Canonical mapping (CDM predicate URI local part -> canonical column name).
# Anchor on URI local parts (stable) rather than rdfs:label (drifts).
# ---------------------------------------------------------------------------

CDM_PREDICATE_TO_CANONICAL: Dict[str, str] = {
    # --- core identifiers ---
    "resource_legal_id_celex": "celex",
    "case-law_ecli": "ecli",
    "resource_legal_id_sector": "sector",
    "resource_legal_type": "resource_legal_type",
    "resource_legal_year": "year_of_resource",
    "resource_legal_number_natural_celex": "natural_number_celex",
    "resource_legal_id_local": "local_identifier",
    "work_has_resource-type": "resource_type",
    "work_id_document": "alternate_identifiers",
    "work_version": "work_version",
    # --- dates ---
    "work_date_document": "date_publication",
    "resource_legal_date_request_opinion": "date_of_request",
    "lastModificationDate": "date_of_creation",
    "creationDate": "creation_date",
    "work_date_creation_legacy": "work_date_creation_legacy",
    # --- legal classification ---
    "resource_legal_based_on_concept_treaty": "based_on_treaty",
    "resource_legal_is_about_subject-matter": "subject_matter",
    "case-law_national-judgement": "national_judgement",
    "case-law_article_journal_related": "references_journals",
    # --- court / parties ---
    "case-law_delivered_by_court-formation": "delivered_by_court_formation",
    "case-law_has_procjur": "judicial_procedure_type",
    "case-law_has_type_procedure_concept_type_procedure": "type_procedure",
    "case-law_has_conclusions_opinion_advocate-general": "conclusions",
    "case-law_interpretes_resource_legal": "legal_resource",
    "case-law_originates_in_country": "origin_country",
    "case-law_originates_in_country_role-qualifier": "origin_country_or_role_qualifier",
    "case-law_uses_procedure_language": "language_procedure",
    "case-law_commented_by_agent": "commented_by_agent",
    # --- legislation-specific (sector 3 / sector 0) ---
    "resource_legal_eli": "eli",
    "resource_legal_in-force": "in_force",
    "resource_legal_eea": "is_eea_relevant",
    "resource_legal_codified_version": "is_codified_version",
    "resource_legal_date_signature": "date_signature",
    "resource_legal_date_end-of-validity": "date_end_of_validity",
    "resource_legal_responsibility_of_agent": "responsibility_agent",
    "resource_legal_comment_internal": "internal_status_code",
    "resource_legal_repertoire": "repertoire",
    "resource_legal_reference_oj-act": "oj_reference",
    "resource_legal_domain_reference_oj-act": "oj_domain_reference",
    "resource_legal_manuscript_ref": "manuscript_ref",
}


# ---------------------------------------------------------------------------
# CDM predicates that should never appear in the output (internal RDF plumbing).
# ---------------------------------------------------------------------------

CDM_PREDICATE_DENYLIST = {
    "do_not_index",
    "memberList",
}


# ---------------------------------------------------------------------------
# Affecting / relation predicates used by _collect_affecting in
# eurlex_scraping.py to derive affecting_ids and affecting_string from
# InfoCuria + CDM relation triples.
# ---------------------------------------------------------------------------

CDM_AFFECTING_PREDICATES = (
    "case-law_amends_resource_legal",
    "case-law_confirms_resource_legal",
    "case-law_declares_void_resource_legal",
    "case-law_joins_case_court",
    "case-law_referred_to_for_preliminary_ruling_case-law",
    "opinion_advocate-general_joined_to_case_court",
)


# ---------------------------------------------------------------------------
# FIELD_MANIFEST — the comprehensive catalogue.
#
# Each entry documents ONE field the package may emit. Categories:
#   - cdm        : flattened from a CDM SPARQL predicate (CELLAR ontology)
#   - infocuria  : extracted from InfoCuria's procedure / document hit JSON
#   - enrichment : computed by add_sections / add_citations_separate
#   - text       : per-document text payload + provenance
#   - rest       : sourced from the CELLAR REST shortcut (sector 3 / sector 0)
#
# Sector affinity values:
#   - any              : populated for both case law and legislation
#   - case_law         : sectors 6 + 8
#   - legislation      : sectors 3 + 0
#   - sector_8         : national case law only
#   - sector_3         : secondary legislation only
#   - rare             : <10% prevalence anywhere
#
# Cardinality:
#   - single           : at most one value per row
#   - multi            : `;`-joined list of values
# ---------------------------------------------------------------------------


def _entry(
    name: str,
    description: str,
    *,
    source: str,
    source_uri: Optional[str] = None,
    canonical: bool = True,
    cardinality: str = "single",
    sector_affinity: str = "any",
    type_: str = "string",
    example: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "source": source,
        "source_uri": source_uri,
        "canonical": canonical,
        "cardinality": cardinality,
        "sector_affinity": sector_affinity,
        "type": type_,
        "example": example,
    }


FIELD_MANIFEST: List[Dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # A. Core identifiers
    # -----------------------------------------------------------------------
    _entry(
        "celex",
        "CELEX identifier(s) — sector + year + type-letter + number, with optional consolidation suffix for sector 0. Multi-valued when an ECLI bundles multiple works (e.g. judgment CELEX + summary CELEX with ``_RES`` suffix). For uniqueness use ``ecli`` as the primary key.",
        source="cdm",
        source_uri="resource_legal_id_celex",
        cardinality="multi",
        sector_affinity="any",
        example="62024CJ0072",
    ),
    _entry(
        "ecli",
        "European Case Law Identifier. Empty for legislation.",
        source="cdm",
        source_uri="case-law_ecli",
        sector_affinity="case_law",
        example="ECLI:EU:C:2026:51",
    ),
    _entry(
        "sector",
        "CELEX sector. 0 consolidated, 3 secondary legislation, 6 CJEU case law, 8 national case law, etc.",
        source="cdm",
        source_uri="resource_legal_id_sector",
        type_="string",
        sector_affinity="any",
        example="6",
    ),
    _entry(
        "resource_legal_type",
        "CELEX type-letter (CJ, CO, CC, R, L, D, …).",
        source="cdm",
        source_uri="resource_legal_type",
        sector_affinity="any",
        example="CO",
    ),
    _entry(
        "year_of_resource",
        "Year embedded in the CELEX.",
        source="cdm",
        source_uri="resource_legal_year",
        type_="integer",
        sector_affinity="any",
        example="2023",
    ),
    _entry(
        "natural_number_celex",
        "Numeric tail of the CELEX (e.g. 800 for 62023CO0800).",
        source="cdm",
        source_uri="resource_legal_number_natural_celex",
        type_="integer",
        sector_affinity="any",
        example="800",
    ),
    _entry(
        "local_identifier",
        "Court-issued local identifier (national case numbers etc.).",
        source="cdm",
        source_uri="resource_legal_id_local",
        sector_affinity="sector_8",
        example="20 Cdo 1073/2025",
    ),
    _entry(
        "alternate_identifiers",
        "All alternate identifier schemes for this work (celex:, ecli:, oj:, eli:, immc:).",
        source="cdm",
        source_uri="work_id_document",
        cardinality="multi",
        sector_affinity="any",
        example="celex:62023CO0800;ecli:ECLI:EU:C:2025:1",
    ),
    _entry(
        "work_version",
        "Version label(s), e.g. definitive, rectified/1. Multi-valued when an ECLI bundles works at different revision states.",
        source="cdm",
        source_uri="work_version",
        cardinality="multi",
        sector_affinity="any",
        example="definitive",
    ),
    # -----------------------------------------------------------------------
    # B. Document type
    # -----------------------------------------------------------------------
    _entry(
        "resource_type",
        "Document type label resolved via skos:prefLabel — Judgment, Order, Opinion of the Advocate General, Decision, Regulation, Directive, etc.",
        source="cdm",
        source_uri="work_has_resource-type",
        cardinality="multi",
        sector_affinity="any",
        example="Order",
    ),
    # -----------------------------------------------------------------------
    # C. Dates
    # -----------------------------------------------------------------------
    _entry(
        "date_publication",
        "Document delivery / publication date(s). Multi-valued when one ECLI bundles works delivered on different dates (e.g. judgment + summary on separate days).",
        source="cdm",
        source_uri="work_date_document",
        type_="date",
        cardinality="multi",
        sector_affinity="any",
        example="2025-01-07",
    ),
    _entry(
        "date_of_request",
        "Date of request for an Opinion / preliminary ruling lodgement.",
        source="cdm",
        source_uri="resource_legal_date_request_opinion",
        type_="date",
        sector_affinity="case_law",
        example="2023-12-28",
    ),
    _entry(
        "date_of_creation",
        "Most recent CMR last-modified timestamp (multi-valued ;-joined when re-indexed).",
        source="cdm",
        source_uri="lastModificationDate",
        type_="datetime",
        cardinality="multi",
        sector_affinity="any",
        example="2026-04-17T20:56:41.157+02:00",
    ),
    _entry(
        "creation_date",
        "Original CMR record-creation timestamp(s). Multi-valued when an ECLI bundles multiple works (each with its own CMR record).",
        source="cdm",
        source_uri="creationDate",
        type_="datetime",
        cardinality="multi",
        sector_affinity="any",
        example="2025-01-15T07:49:16.490+01:00",
    ),
    _entry(
        "work_date_creation_legacy",
        "Legacy creation date(s) carried from before the modern CMR. Multi-valued when an ECLI bundles multiple works.",
        source="cdm",
        source_uri="work_date_creation_legacy",
        type_="date",
        cardinality="multi",
        sector_affinity="any",
        example="2025-01-15",
    ),
    _entry(
        "date_signature",
        "Date the legal act was signed.",
        source="cdm",
        source_uri="resource_legal_date_signature",
        type_="date",
        sector_affinity="legislation",
        example="2016-04-27",
    ),
    _entry(
        "date_end_of_validity",
        "End-of-validity date (often 9999-12-31 = act still active).",
        source="cdm",
        source_uri="resource_legal_date_end-of-validity",
        type_="date",
        sector_affinity="legislation",
        example="9999-12-31",
    ),
    # -----------------------------------------------------------------------
    # D. Court / parties / agents
    # -----------------------------------------------------------------------
    _entry(
        "delivered_by_court_formation",
        "Court formation that delivered the judgment, e.g. Tenth Chamber, Grand Chamber.",
        source="cdm",
        source_uri="case-law_delivered_by_court-formation",
        sector_affinity="case_law",
        example="Tenth Chamber",
    ),
    _entry(
        "commented_by_agent",
        "Member states / EU institutions that submitted observations.",
        source="cdm",
        source_uri="case-law_commented_by_agent",
        cardinality="multi",
        sector_affinity="case_law",
        example="Belgium;EU institutions and bodies;European Commission",
    ),
    _entry(
        "advocate_general",
        "Surname (with optional initial) of the Advocate General — InfoCuria-resolved name.",
        source="infocuria",
        source_uri="advocateML",
        sector_affinity="case_law",
        example="Campos Sánchez-Bordona",
    ),
    _entry(
        "judge_rapporteur",
        "Surname of the Judge Rapporteur — InfoCuria-resolved name.",
        source="infocuria",
        source_uri="reportingJudgeML",
        sector_affinity="case_law",
        example="Smulders",
    ),
    # -----------------------------------------------------------------------
    # E. Procedure
    # -----------------------------------------------------------------------
    _entry(
        "judicial_procedure_type",
        "Broad procedural class. Multi-valued for joined cases or rows aggregating multiple works of different procedural types.",
        source="cdm",
        source_uri="case-law_has_procjur",
        cardinality="multi",
        sector_affinity="case_law",
        example="Reference for a preliminary ruling",
    ),
    _entry(
        "type_procedure",
        "Refined procedural label, often with state qualifier. Multi-valued for the same reason as judicial_procedure_type.",
        source="cdm",
        source_uri="case-law_has_type_procedure_concept_type_procedure",
        cardinality="multi",
        sector_affinity="case_law",
        example="Reference for a preliminary ruling - inadmissible",
    ),
    _entry(
        "language_procedure",
        "Procedural language.",
        source="cdm",
        source_uri="case-law_uses_procedure_language",
        sector_affinity="case_law",
        example="Dutch",
    ),
    _entry(
        "origin_country",
        "Country of origin (referring court for preliminary rulings, action-respondent for direct actions).",
        source="cdm",
        source_uri="case-law_originates_in_country",
        cardinality="multi",
        sector_affinity="case_law",
        example="Belgium",
    ),
    _entry(
        "origin_country_or_role_qualifier",
        "Country of origin enriched with role qualifier (respondent / applicant).",
        source="cdm",
        source_uri="case-law_originates_in_country_role-qualifier",
        cardinality="multi",
        sector_affinity="case_law",
        example="Belgium",
    ),
    _entry(
        "conclusions",
        "Reference (CELLAR URI) to the Advocate-General's Opinion linked to this case.",
        source="cdm",
        source_uri="case-law_has_conclusions_opinion_advocate-general",
        sector_affinity="case_law",
        example="http://publications.europa.eu/resource/cellar/8e01d479-…",
    ),
    _entry(
        "legal_resource",
        "Legal resource (statute, treaty article, regulation, …) the case interprets.",
        source="cdm",
        source_uri="case-law_interpretes_resource_legal",
        cardinality="multi",
        sector_affinity="case_law",
        example="http://publications.europa.eu/resource/cellar/4fd758c9-…",
    ),
    # -----------------------------------------------------------------------
    # F. Subject matter / classification
    # -----------------------------------------------------------------------
    _entry(
        "subject_matter",
        "Top-level subject matter taxonomy.",
        source="cdm",
        source_uri="resource_legal_is_about_subject-matter",
        cardinality="multi",
        sector_affinity="any",
        example="Free movement of goods;Customs Union and Common Customs Tariff",
    ),
    _entry(
        "directory_codes",
        "EUR-Lex case-law directory codes (LCMA, FISC, …).",
        source="infocuria",
        source_uri="matCode",
        cardinality="multi",
        sector_affinity="case_law",
        example="DFON;LCMA;PRIN",
    ),
    _entry(
        "eurovoc",
        "EuroVoc concept labels (resolved EN).",
        source="infocuria",
        source_uri="matCodeML",
        cardinality="multi",
        sector_affinity="case_law",
        example="Fundamental rights;Free movement of goods",
    ),
    _entry(
        "keywords",
        "Keyword surface form of eurovoc; same content as eurovoc on most rows for backwards compatibility.",
        source="infocuria",
        source_uri="matCodeML",
        cardinality="multi",
        sector_affinity="case_law",
        example="Fundamental rights;Free movement of goods",
    ),
    _entry(
        "based_on_treaty",
        "Treaty basis. Populated both for legislative acts (the treaty article(s) the act is based on) and for case-law documents that interpret a treaty.",
        source="cdm",
        source_uri="resource_legal_based_on_concept_treaty",
        cardinality="multi",
        sector_affinity="any",
        example="Treaty on the Functioning of the European Union (consolidated version 2012)",
    ),
    # -----------------------------------------------------------------------
    # G. Legislation-specific
    # -----------------------------------------------------------------------
    _entry(
        "eli",
        "European Legislation Identifier — canonical URL of the act.",
        source="cdm",
        source_uri="resource_legal_eli",
        type_="url",
        sector_affinity="legislation",
        example="http://data.europa.eu/eli/reg/2016/679/oj",
    ),
    _entry(
        "in_force",
        "Boolean flag: is the act still in force?",
        source="cdm",
        source_uri="resource_legal_in-force",
        type_="boolean",
        sector_affinity="legislation",
        example="1",
    ),
    _entry(
        "is_eea_relevant",
        "Boolean flag: is the act EEA-relevant?",
        source="cdm",
        source_uri="resource_legal_eea",
        type_="boolean",
        sector_affinity="legislation",
        example="1",
    ),
    _entry(
        "is_codified_version",
        "Boolean flag: is this act a codified version?",
        source="cdm",
        source_uri="resource_legal_codified_version",
        type_="boolean",
        sector_affinity="legislation",
        example="0",
    ),
    _entry(
        "repertoire",
        "Repertoire-of-legislation-in-force flag (REP).",
        source="cdm",
        source_uri="resource_legal_repertoire",
        sector_affinity="legislation",
        example="REP",
    ),
    _entry(
        "oj_reference",
        "Compact OJ reference (e.g. 2024/1689).",
        source="cdm",
        source_uri="resource_legal_reference_oj-act",
        sector_affinity="legislation",
        example="2024/1689",
    ),
    _entry(
        "oj_domain_reference",
        "OJ act domain (e.g. EU).",
        source="cdm",
        source_uri="resource_legal_domain_reference_oj-act",
        sector_affinity="legislation",
        example="EU",
    ),
    _entry(
        "manuscript_ref",
        "Manuscript reference for the OJ submission.",
        source="cdm",
        source_uri="resource_legal_manuscript_ref",
        sector_affinity="legislation",
        example="PE 17 2016 INIT",
    ),
    _entry(
        "responsibility_agent",
        "Responsible Commission DG / agent.",
        source="cdm",
        source_uri="resource_legal_responsibility_of_agent",
        cardinality="multi",
        sector_affinity="legislation",
        example="Eurostat;Directorate-General for Justice and Consumers",
    ),
    _entry(
        "internal_status_code",
        "Internal CMR status code (MAN1, MAN2, …).",
        source="cdm",
        source_uri="resource_legal_comment_internal",
        sector_affinity="legislation",
        example="MAN2",
    ),
    # -----------------------------------------------------------------------
    # H. National-judgement passthrough (sector 6 + sector 8)
    # -----------------------------------------------------------------------
    _entry(
        "national_judgement",
        "Raw <national_judgement> XML block — referring national court, decision date, case ids. Multi-valued when an ECLI bundles multiple works each carrying their own block.",
        source="cdm",
        source_uri="case-law_national-judgement",
        type_="xml",
        cardinality="multi",
        sector_affinity="case_law",
        example="<national_judgement>…</national_judgement>",
    ),
    _entry(
        "references_journals",
        "References to journal articles indexing the case.",
        source="cdm",
        source_uri="case-law_article_journal_related",
        cardinality="multi",
        sector_affinity="case_law",
        example="<related_journal_articles>…</related_journal_articles>",
    ),
    # -----------------------------------------------------------------------
    # I. Citation graph & affecting relations
    # -----------------------------------------------------------------------
    _entry(
        "citing",
        "CELEX ids of works this document cites (out-edges).",
        source="enrichment",
        cardinality="multi",
        sector_affinity="any",
        example="32012Q0929(01);62015CO0328",
    ),
    _entry(
        "cited_by",
        "CELEX ids of works that cite this document (in-edges).",
        source="enrichment",
        cardinality="multi",
        sector_affinity="any",
        example="62025CO0114",
    ),
    _entry(
        "affecting_ids",
        "Clean published case numbers of affecting cases (joined / appealed / re-examined / transferred).",
        source="infocuria",
        cardinality="multi",
        sector_affinity="case_law",
        example="C-73/24",
    ),
    _entry(
        "affecting_string",
        "Affecting cases prefixed with relation kind: joined / appeal_against / appealed_in / re-examines / re-examined_in / transfers / transferred_from.",
        source="infocuria",
        cardinality="multi",
        sector_affinity="case_law",
        example="joined: C-73/24",
    ),
    _entry(
        "citations_extra_info",
        "Composite of party names + procedure result type (free-text).",
        source="infocuria",
        sector_affinity="case_law",
        example="DRINKS 52;Reference for a preliminary ruling: dismissal on grounds of inadmissibility",
    ),
    # -----------------------------------------------------------------------
    # J. Texts and provenance
    # -----------------------------------------------------------------------
    _entry(
        "summary",
        "Plain-text summary of the case (preliminary-ruling summary, judgment abstract). Sector 6 only.",
        source="infocuria",
        sector_affinity="case_law",
        example="Summary C-800/23 — 1\nCase C-800/23\n…",
    ),
    _entry(
        "text_source",
        "Provenance of the full text: INFOCURIA_BLOB_HTML, CELLAR_ITEM, CELLAR_REST_XHTML, EXTRACTOR_FALLBACK_TEXT, or empty.",
        source="enrichment",
        sector_affinity="any",
        example="INFOCURIA_BLOB_HTML",
    ),
    _entry(
        "text_format",
        "html, xhtml, pdf, xml, or empty.",
        source="enrichment",
        sector_affinity="any",
        example="html",
    ),
    _entry(
        "text_language",
        "ISO-639-1 language code of the full text (EN, DE, …).",
        source="enrichment",
        sector_affinity="any",
        example="EN",
    ),
    _entry(
        "summary_source",
        "Provenance of the summary: INFOCURIA_DOCUMENT_CONTENT, INFOCURIA_AFF_OBJECT, CELLAR_SUMMARY_ITEM, or empty.",
        source="enrichment",
        sector_affinity="case_law",
        example="INFOCURIA_DOCUMENT_CONTENT",
    ),
    _entry(
        "summary_language",
        "Language of the summary text.",
        source="enrichment",
        sector_affinity="case_law",
        example="EN",
    ),
    _entry(
        "fulltext_source",
        "Mirror of text_source written into the metadata CSV column for backwards compatibility.",
        source="enrichment",
        sector_affinity="any",
        example="INFOCURIA_BLOB_HTML",
    ),
    _entry(
        "missing_reasons",
        "`;`-joined flags marking absent upstream content. Empty when retrieval was complete.",
        source="enrichment",
        cardinality="multi",
        sector_affinity="any",
        example="FULLTEXT_UNAVAILABLE_UPSTREAM;SUMMARY_UNAVAILABLE_UPSTREAM",
    ),
]


# ---------------------------------------------------------------------------
# Derived constants used by the rest of the package.
# ---------------------------------------------------------------------------

CANONICAL_COLUMNS: List[str] = sorted(
    {field["name"] for field in FIELD_MANIFEST if field.get("canonical")}
)


# Backwards-compatible alias for the enrichment-only column names — kept so
# existing imports keep working. The manifest is now the source of truth.
ENRICHMENT_CANONICAL_COLUMNS = tuple(
    field["name"]
    for field in FIELD_MANIFEST
    if field.get("source") == "enrichment" and field.get("canonical")
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def cdm_local_part(predicate_uri: str) -> str:
    """Return the local part of a CDM predicate URI (without namespace)."""
    if not isinstance(predicate_uri, str):
        return ""
    if "#" in predicate_uri:
        return predicate_uri.rsplit("#", 1)[-1]
    return predicate_uri.rsplit("/", 1)[-1]


def cdm_canonical_name(predicate_local: str) -> Optional[str]:
    """Map a CDM predicate's URI local part to its canonical column name.

    Returns ``None`` for denylisted predicates. For predicates without an
    explicit canonical entry, derives a deterministic snake_case fallback name
    from the local part — so no data is ever silently dropped.
    """
    if predicate_local in CDM_PREDICATE_DENYLIST:
        return None
    if predicate_local in CDM_PREDICATE_TO_CANONICAL:
        return CDM_PREDICATE_TO_CANONICAL[predicate_local]
    name = predicate_local
    folded = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper() and name[i - 1] != "_":
            folded.append("_")
        folded.append(ch.lower())
    name = "".join(folded)
    return name.replace("-", "_").replace(".", "_").replace("/", "_")


def fill_canonical(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``row`` with every CANONICAL_COLUMNS key present.

    Existing keys are left untouched. Missing canonical keys are added with
    value ``None``. Non-canonical keys (discovered fallbacks) are preserved so
    callers see the union.
    """
    out: Dict[str, Any] = {col: None for col in CANONICAL_COLUMNS}
    for k, v in row.items():
        out[k] = v
    return out


def describe(canonical_only: bool = False) -> List[Dict[str, Any]]:
    """Return the package's field manifest as plain dicts.

    Use this for programmatic introspection — building a downstream loader,
    deriving a JSON-Schema, or rendering documentation. The returned list is
    a deep-enough copy that mutating it won't affect the package globals.
    """
    if canonical_only:
        return [dict(f) for f in FIELD_MANIFEST if f.get("canonical")]
    return [dict(f) for f in FIELD_MANIFEST]
