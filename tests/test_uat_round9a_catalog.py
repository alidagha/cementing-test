"""Round 9A catalog/product foundation; no calculation, UI or project state."""
import hashlib
import importlib
import importlib.util
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

import materials_db


ROOT = Path(__file__).resolve().parents[1]
ENGINE_SHA = "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9"
COMPANION_SHA = "68b275c0c3fd0e804a926d39e1123b451f7e22b2c5aad31f6d0ab3e8236709d4"
# Canonical JSON of the hash-verified raw owner catalog, before adding kind.
SOURCE_VALUES_SHA = "fc3cf90e38342eccf5c6f2349dac0cd1fc7cb3de9c5266440cb98214e0376d1a"


def adapter():
    assert importlib.util.find_spec("centralizer_adapter"), "Round 9A product adapter is absent"
    return importlib.import_module("centralizer_adapter")


def catalog():
    return adapter().load_official_catalog()


@pytest.mark.parametrize("name,expected", [
    ("centralizer_optimizer_engine.py", ENGINE_SHA),
    ("cement_charts_engine.py", COMPANION_SHA),
])
def test_certified_artifacts_are_byte_identical(name, expected):
    path = ROOT / name
    assert path.is_file(), f"Certified artifact {name} is absent"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_engine_version_and_product_contract():
    assert importlib.util.find_spec("centralizer_optimizer_engine"), "Certified engine is absent"
    engine = importlib.import_module("centralizer_optimizer_engine")
    assert engine.__version__ == "1.2.9"
    mapped = adapter().to_engine_product(catalog()[0])
    assert set(mapped) == set(engine.CentralizerProduct.__dataclass_fields__)
    product = engine.CentralizerProduct(**mapped)
    assert product.name == mapped["name"]
    assert product.kind == mapped["kind"]


def test_catalog_count_unique_nr_and_exact_classification_census():
    products = catalog()
    document = json.loads((ROOT / "ds_cent_products.json").read_text())
    assert document["n_products"] == len(document["products"]) == len(products) == 4692
    assert all(isinstance(row["nr"], int) and not isinstance(row["nr"], bool) for row in products)
    assert len({row["nr"] for row in products}) == 4692
    assert Counter(row["kind"] for row in products) == {"rigid": 3660, "spring": 1032}
    assert all(row["kind"] == adapter().official_product_kind(row) for row in products)


def test_every_original_catalog_value_metadata_and_order_is_preserved():
    document = json.loads((ROOT / "ds_cent_products.json").read_text())
    for row in document["products"]:
        assert row.pop("kind") in ("rigid", "spring")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canonical.encode()).hexdigest() == SOURCE_VALUES_SHA


@pytest.mark.parametrize("rf,api,expected", [
    (None, None, "rigid"), (None, 0, "rigid"), (0, None, "rigid"),
    (0, 0, "rigid"), (0.0, 0.0, "rigid"),
    (1, 0, "spring"), (0, 1, "spring"), (1, 1, "spring"),
    (None, 1, "spring"), (1, None, "spring"), (-1, 0, "spring"),
])
def test_official_rule_r_star(rf, api, expected):
    row = {"restoring_force_lbf": rf, "api_rf_lbf": api}
    assert adapter().official_product_kind(row) == expected


@pytest.mark.parametrize("extra", [
    {"description": "RIGID SOLID"}, {"type": "SPRING"},
    {"bow_type": "Rigid"}, {"bows": 16}, {"bows": 0},
    {"identification": "SPRING RIGID"}, {"name": "BOW SPRING"},
    {"manufacturer": "Rigid manufacturer"}, {"max_od_in": 12, "min_od_in": 1},
])
def test_classification_ignores_all_text_bows_and_dimension_hints(extra):
    assert adapter().official_product_kind(extra) == "rigid"  # Missing forces still use R*.
    assert adapter().official_product_kind({**extra, "restoring_force_lbf": 0, "api_rf_lbf": 1}) == "spring"


@pytest.mark.parametrize("value", [True, "0", float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["restoring_force_lbf", "api_rf_lbf"])
def test_malformed_authoritative_force_is_not_silently_classified(field, value):
    with pytest.raises(ValueError, match=field):
        adapter().official_product_kind({field: value})


def test_duplicate_identification_resolves_by_nr_across_json_and_reordering():
    products = catalog()
    first = adapter().resolve_official_product(products, 102)
    second = adapter().resolve_official_product(products, 105)
    assert first["identification"] == second["identification"]
    assert first["nr"] != second["nr"]
    saved = json.loads(json.dumps({"product_nr": second["nr"]}))
    restored = adapter().resolve_official_product(list(reversed(products)), saved["product_nr"])
    assert restored == second
    assert adapter().to_engine_product(first)["name"] != adapter().to_engine_product(second)["name"]
    assert adapter().to_engine_product(restored)["name"] == adapter().to_engine_product(second)["name"]


@pytest.mark.parametrize("nr", [None, True, "25", 25.0, -999])
def test_invalid_or_unrecognized_product_identity_never_selects_a_default(nr):
    with pytest.raises(ValueError, match="nr"):
        adapter().resolve_official_product(catalog(), nr)


@pytest.mark.parametrize("size,expected", [(7, 7.0), ('7"', 7.0), ("9 5/8", 9.625), (9.625, 9.625), ("2 7/8", 2.875)])
def test_numeric_pipe_size_filter_reuses_fractional_size_authority(size, expected):
    products = catalog()
    result = adapter().filter_official_products(products, size)
    assert isinstance(result, list) and len(result) > 1
    assert all(row["pipe_size_in"] == expected for row in result)
    assert result == [row for row in products if row["pipe_size_in"] == expected]


def test_pipe_filter_keeps_every_hole_size_and_returns_candidates_only():
    products = catalog()
    selected = adapter().filter_official_products(products, 7)
    assert len(selected) == 346
    assert len({row["hole_size_in"] for row in selected}) > 1
    assert adapter().filter_official_products(products, 31) == []
    assert adapter().filter_official_products([selected[0]], 7) == [selected[0]]


@pytest.mark.parametrize("size", [None, True, 0, -1, "-7", "-9 5/8", '"-7"', '"-9 5/8"', "", "not a size", float("nan"), float("inf")])
def test_invalid_pipe_size_fails_without_guessing(size):
    with pytest.raises(ValueError, match="[Pp]ipe size"):
        adapter().filter_official_products(catalog(), size)


def test_engine_mapping_exact_si_fields_and_no_source_mutation():
    row = adapter().resolve_official_product(catalog(), 25)
    before = deepcopy(row)
    mapped = adapter().to_engine_product(row)
    assert mapped == {
        "name": "OFFICIAL-CENT-25", "code": "25", "kind": "spring", "bows": row["bows"],
        "max_od": row["max_od_in"] * 0.0254,
        "min_od": row["min_od_in"] * 0.0254,
        "starting_force": row["starting_force_lbf"] * 4.4482216152605,
        "running_force": row["running_force_lbf"] * 4.4482216152605,
        "restoring_force": row["restoring_force_lbf"] * 4.4482216152605,
        "rated_hole": row["hole_size_in"] * 0.0254,
        "manufacturer": row["manufacturer"], "description": row["description"],
    }
    assert row == before
    assert "api_rf_lbf" not in mapped


def test_all_engine_names_and_codes_are_unique_and_stable():
    products = catalog()
    mapped = [adapter().to_engine_product(row) for row in products]
    assert len({row["name"] for row in mapped}) == len({row["code"] for row in mapped}) == 4692
    assert [adapter().to_engine_product(row)["name"] for row in reversed(products)] == [row["name"] for row in reversed(mapped)]
    assert [row["kind"] for row in mapped] == [row["kind"] for row in products]


@pytest.mark.parametrize("mutation,message", [
    ("count", "count"), ("duplicate_nr", "nr"), ("missing_nr", "nr"),
    ("kind", "kind"), ("nonfinite_force", "restoring_force_lbf"),
])
def test_corrupt_catalog_fails_controlled_validation(tmp_path, mutation, message):
    document = json.loads((ROOT / "ds_cent_products.json").read_text())
    if mutation == "count":
        document["n_products"] -= 1
    elif mutation == "duplicate_nr":
        document["products"][1]["nr"] = document["products"][0]["nr"]
    elif mutation == "missing_nr":
        del document["products"][0]["nr"]
    elif mutation == "kind":
        document["products"][0]["kind"] = "rigid"
    else:
        document["products"][0]["restoring_force_lbf"] = float("inf")
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match=message):
        adapter().load_official_catalog(path)


@pytest.mark.parametrize("job", materials_db.JOB_TYPES)
def test_exact_current_job_applicability(job):
    assert adapter().centralizer_applicable(job) is (job not in ("CMT PLUG", "CMT SQUEEZE"))


@pytest.mark.parametrize("job", ["", 'CSG 42"', 'TIE BACK LNR 9 5/8"', "NEW LINER"])
def test_unknown_jobs_are_not_inferred_from_substrings(job):
    assert adapter().centralizer_applicable(job) is False
