"""Unit tests for the canonical schema manifest.

These tests run offline. They lock down the contract that
``cellar_extractor.schema`` exposes so future edits to ``FIELD_MANIFEST`` can't
silently drop a canonical field, mis-tag a source, or break the URI-to-canonical
mapping.
"""

import pytest

from cellar_extractor import schema


# ---------------------------------------------------------------------------
# Manifest shape & invariants
# ---------------------------------------------------------------------------


def test_manifest_entries_have_required_keys():
    required = {
        "name",
        "description",
        "source",
        "source_uri",
        "canonical",
        "cardinality",
        "sector_affinity",
        "type",
        "example",
    }
    for entry in schema.FIELD_MANIFEST:
        missing = required - set(entry)
        assert not missing, f"manifest entry {entry.get('name')!r} missing keys {missing}"


def test_manifest_names_are_unique():
    names = [entry["name"] for entry in schema.FIELD_MANIFEST]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"duplicate names in FIELD_MANIFEST: {duplicates}"


def test_manifest_names_are_lowercase_snake_case():
    for entry in schema.FIELD_MANIFEST:
        name = entry["name"]
        assert name == name.lower(), f"non-lowercase canonical name: {name!r}"
        assert " " not in name, f"whitespace in canonical name: {name!r}"
        assert "-" not in name, f"hyphen in canonical name: {name!r}"


def test_canonical_columns_matches_manifest_canonical_set():
    manifest_canonical = sorted({e["name"] for e in schema.FIELD_MANIFEST if e.get("canonical")})
    assert schema.CANONICAL_COLUMNS == manifest_canonical


def test_manifest_source_values_are_known():
    allowed = {"cdm", "infocuria", "enrichment", "rest"}
    for entry in schema.FIELD_MANIFEST:
        assert entry["source"] in allowed, (
            f"unknown source {entry['source']!r} on {entry['name']!r}"
        )


def test_manifest_cardinality_values_are_known():
    allowed = {"single", "multi"}
    for entry in schema.FIELD_MANIFEST:
        assert entry["cardinality"] in allowed, (
            f"unknown cardinality {entry['cardinality']!r} on {entry['name']!r}"
        )


def test_manifest_sector_affinity_values_are_known():
    allowed = {"any", "case_law", "legislation", "sector_8", "sector_3", "rare"}
    for entry in schema.FIELD_MANIFEST:
        assert entry["sector_affinity"] in allowed, (
            f"unknown sector_affinity {entry['sector_affinity']!r} on {entry['name']!r}"
        )


def test_manifest_type_values_are_known():
    allowed = {"string", "integer", "date", "datetime", "boolean", "url", "xml"}
    for entry in schema.FIELD_MANIFEST:
        assert entry["type"] in allowed, (
            f"unknown type {entry['type']!r} on {entry['name']!r}"
        )


# ---------------------------------------------------------------------------
# CDM predicate URI mapping
# ---------------------------------------------------------------------------


def test_every_cdm_canonical_target_appears_in_manifest():
    """Each value in CDM_PREDICATE_TO_CANONICAL must have a manifest entry."""
    canonical_targets = set(schema.CDM_PREDICATE_TO_CANONICAL.values())
    manifest_names = {e["name"] for e in schema.FIELD_MANIFEST}
    missing = canonical_targets - manifest_names
    assert not missing, f"CDM mapping points at names not in manifest: {missing}"


def test_cdm_mapping_source_uris_match_manifest():
    """For CDM-sourced canonical fields, source_uri must be a key in CDM_PREDICATE_TO_CANONICAL."""
    inverse = {v: k for k, v in schema.CDM_PREDICATE_TO_CANONICAL.items()}
    for entry in schema.FIELD_MANIFEST:
        if entry["source"] != "cdm" or not entry.get("canonical"):
            continue
        canonical_name = entry["name"]
        if canonical_name in inverse:
            assert entry["source_uri"] == inverse[canonical_name], (
                f"manifest source_uri mismatch for {canonical_name!r}: "
                f"manifest says {entry['source_uri']!r}, "
                f"CDM_PREDICATE_TO_CANONICAL inverse says {inverse[canonical_name]!r}"
            )


def test_cdm_denylist_predicates_not_in_canonical_map():
    overlap = set(schema.CDM_PREDICATE_DENYLIST) & set(schema.CDM_PREDICATE_TO_CANONICAL)
    assert not overlap, f"predicate is both denylisted and canonical: {overlap}"


# ---------------------------------------------------------------------------
# cdm_canonical_name() behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "predicate_local,expected",
    [
        ("resource_legal_id_celex", "celex"),
        ("case-law_ecli", "ecli"),
        ("resource_legal_eli", "eli"),
        ("work_has_resource-type", "resource_type"),
        ("lastModificationDate", "date_of_creation"),
    ],
)
def test_cdm_canonical_name_explicit_mapping(predicate_local, expected):
    assert schema.cdm_canonical_name(predicate_local) == expected


@pytest.mark.parametrize("predicate_local", schema.CDM_PREDICATE_DENYLIST)
def test_cdm_canonical_name_denylist_returns_none(predicate_local):
    assert schema.cdm_canonical_name(predicate_local) is None


@pytest.mark.parametrize(
    "predicate_local,expected_fallback",
    [
        # Hyphens collapse to underscores
        ("case-law_amends_resource_legal", "case_law_amends_resource_legal"),
        # camelCase splits at boundaries
        ("workCitesWork", "work_cites_work"),
        # Dots and slashes also fold
        ("foo.bar/baz", "foo_bar_baz"),
        # Already snake_case stays the same
        ("work_cites_work", "work_cites_work"),
    ],
)
def test_cdm_canonical_name_fallback(predicate_local, expected_fallback):
    """Predicates without an explicit canonical entry fall back to a deterministic snake_case name."""
    assert schema.cdm_canonical_name(predicate_local) == expected_fallback


def test_cdm_local_part_extracts_after_hash_or_slash():
    assert schema.cdm_local_part("http://publications.europa.eu/ontology/cdm#case-law_ecli") == "case-law_ecli"
    assert schema.cdm_local_part("http://example.org/foo/bar") == "bar"
    assert schema.cdm_local_part("") == ""
    assert schema.cdm_local_part(None) == ""


# ---------------------------------------------------------------------------
# fill_canonical() shape contract
# ---------------------------------------------------------------------------


def test_fill_canonical_inserts_every_canonical_key_as_none():
    filled = schema.fill_canonical({})
    assert set(filled) == set(schema.CANONICAL_COLUMNS)
    assert all(v is None for v in filled.values())


def test_fill_canonical_preserves_existing_values():
    seed = {"celex": "62024CJ0072", "summary": "snippet", "discovered_extra": "kept"}
    filled = schema.fill_canonical(seed)
    assert filled["celex"] == "62024CJ0072"
    assert filled["summary"] == "snippet"
    assert filled["discovered_extra"] == "kept"  # discovered fields preserved
    # canonical-but-unset still nulled
    assert filled["ecli"] is None


def test_fill_canonical_does_not_mutate_input():
    seed = {"celex": "X"}
    schema.fill_canonical(seed)
    assert seed == {"celex": "X"}


# ---------------------------------------------------------------------------
# describe() introspection helper
# ---------------------------------------------------------------------------


def test_describe_returns_full_manifest_by_default():
    out = schema.describe()
    assert len(out) == len(schema.FIELD_MANIFEST)


def test_describe_canonical_only_filters():
    out = schema.describe(canonical_only=True)
    assert len(out) == len(schema.CANONICAL_COLUMNS)
    assert all(entry["canonical"] for entry in out)


def test_describe_returns_independent_copies():
    a = schema.describe()
    a[0]["name"] = "MUTATED"
    b = schema.describe()
    assert b[0]["name"] != "MUTATED"


# ---------------------------------------------------------------------------
# Backwards-compat alias kept stable
# ---------------------------------------------------------------------------


def test_enrichment_canonical_columns_subset_of_canonical():
    enrichment = set(schema.ENRICHMENT_CANONICAL_COLUMNS)
    assert enrichment.issubset(set(schema.CANONICAL_COLUMNS))


def test_enrichment_canonical_columns_all_marked_enrichment_in_manifest():
    by_name = {e["name"]: e for e in schema.FIELD_MANIFEST}
    for name in schema.ENRICHMENT_CANONICAL_COLUMNS:
        assert by_name[name]["source"] == "enrichment", (
            f"{name!r} listed in ENRICHMENT_CANONICAL_COLUMNS but manifest source is "
            f"{by_name[name]['source']!r}"
        )
