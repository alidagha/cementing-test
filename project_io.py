"""Parse a project completely before replacing the current session."""
import hashlib
import json
import math
import pandas as pd
import materials_db
from project_state import SLURRIES, is_project_key, restore_canonical_fields


def content_signature(raw_bytes):
    return hashlib.sha256(raw_bytes).hexdigest()


def _reject_constant(token):
    raise ValueError(f"Non-JSON numeric value: {token}")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate project field: {key}")
        result[key] = value
    return result


def _check_finite(value, path="project"):
    """Reject overflowed JSON exponents and invalid numbers in table cells."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must contain a finite number")
    if isinstance(value, pd.DataFrame):
        for index, row in enumerate(value.to_dict("records")):
            for column, cell in row.items():
                # JSON null becomes NaN in a numeric DataFrame column.
                # Allow unfinished table drafts to reopen; the Word export
                # path validates required additive concentrations separately.
                if isinstance(cell, float) and math.isnan(cell):
                    continue
                _check_finite(cell, f"{path}[{index}].{column}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_finite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _check_finite(item, f"{path}[{idx}]")


def _check_numeric_fields(container, fields, path, nullable=()):
    """Reject malformed saved numbers before any session state is replaced."""
    for field in fields:
        if field not in container:
            continue
        value = container[field]
        if value is None and field in nullable:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{path}.{field} must be a finite number (got {value!r}).")


def _validate_project(data):
    if not any(key in data for key in ("job_type", "well_name", "doc_control",
                                       "well_data", "hardware_table", "fluids_config")):
        raise ValueError("No recognizable well or project fields were found.")
    for key in ("job_type", "well_name"):
        if key in data and not isinstance(data[key], str):
            raise ValueError(f"{key} must be text.")
    if "job_type" in data and data["job_type"] not in materials_db.JOB_TYPES:
        raise ValueError("job_type is not supported by this application.")
    for field in ("request_description_customized", "revision_description_customized"):
        if field in data and not isinstance(data[field], bool):
            raise ValueError(f"{field} must be a boolean.")
    schemas = {
        "doc_control": dict, "well_data": dict, "fluids_config": dict,
        "fluid_data": dict, "cement_params": dict, "cement_additives_dfs": dict,
        "lab_grid_dfs": dict, "lab_qc_params": dict, "lab_source_signatures": dict,
        "report_text_state": dict, "placement_config": dict, "spacer_dfs": dict,
        "preflush_config": dict, "hardware_table": pd.DataFrame,
        "hardware_editor_draft": pd.DataFrame,
        "inactive_slurry_drafts": dict,
        "cement_initialized_slurries": list, "lab_initialized_slurries": list,
        "spacer_initialized_names": list, "active_fluids": dict,
    }
    for key, expected in schemas.items():
        if key in data and not isinstance(data[key], expected):
            raise ValueError(f"{key} must be a {expected.__name__}, not {type(data[key]).__name__}.")
    cfg = data.get("fluids_config", {})
    if cfg and (not isinstance(cfg.get("active", []), list)
                or not all(isinstance(x, str) for x in cfg.get("active", []))
                or any(x not in materials_db.FLUID_TYPES for x in cfg.get("active", []))
                or not isinstance(cfg.get("params", {}), dict)
                or any(not isinstance(v, dict) for v in cfg.get("params", {}).values())):
        raise ValueError("fluids_config needs a fluid list and parameter records.")
    for key in ("cement_params", "lab_qc_params", "report_text_state", "fluid_data"):
        if any(not isinstance(item, dict) for item in data.get(key, {}).values()):
            raise ValueError(f"{key} contains an invalid record.")
    for key in ("cement_additives_dfs", "lab_grid_dfs", "spacer_dfs"):
        if any(not isinstance(item, pd.DataFrame) for item in data.get(key, {}).values()):
            raise ValueError(f"{key} contains a table that could not be restored.")
    archived_fields = {"cement_additives_dfs": pd.DataFrame, "cement_params": dict,
                       "lab_grid_dfs": pd.DataFrame, "lab_qc_params": dict}
    for slurry, draft in data.get("inactive_slurry_drafts", {}).items():
        if slurry not in SLURRIES or not isinstance(draft, dict) or any(
                field not in archived_fields or not isinstance(value, archived_fields[field])
                for field, value in draft.items()):
            raise ValueError(f"inactive_slurry_drafts.{slurry} has an invalid formulation.")
        for field, required in (("cement_additives_dfs", {"Material Type", "Name", "Physical State", "Mix Method", "User Input"}),
                                ("lab_grid_dfs", {"Material", "Concentration", "Unit", "Mass", "Lot No"})):
            if field in draft and not required.issubset(draft[field].columns):
                raise ValueError(f"inactive_slurry_drafts.{slurry}.{field} is missing required columns.")
        if "cement_params" in draft:
            _check_numeric_fields(draft["cement_params"], ("yield", "mix_water", "dead_vol", "total_sacks", "cmt_sg"),
                                  f"inactive_slurry_drafts.{slurry}.cement_params",
                                  nullable=("dead_vol",) if slurry == "Main" else ())
        if "lab_qc_params" in draft:
            _check_numeric_fields(draft["lab_qc_params"], ("api_fl", "free_water", "bhct", "free_water_45", "surface_hardened_hours"),
                                  f"inactive_slurry_drafts.{slurry}.lab_qc_params",
                                  nullable=("free_water_45", "surface_hardened_hours", "bhct") if slurry == "Main" else ("free_water_45", "surface_hardened_hours"))
    # Empty well number inputs are valid unfinished drafts, not malformed numbers.
    for container, path in ((data, "project"), (data.get("well_data", {}), "well_data")):
        _check_numeric_fields(container, tuple(field for field in ("geo_md", "geo_tvd", "geo_gradient", "bhst")
                                               if container.get(field) is not None), path)
    auto_fields = data.get("well_auto_fields", {})
    if (not isinstance(auto_fields, dict) or any(field not in ("geo_gradient", "bhsp")
            or not isinstance(enabled, bool) for field, enabled in auto_fields.items())):
        raise ValueError("well_auto_fields must contain boolean Gradient/BHSP provenance.")
    for name, params in cfg.get("params", {}).items():
        _check_numeric_fields(params, ("volume",), f"fluids_config.params.{name}")
    for name, params in data.get("cement_params", {}).items():
        _check_numeric_fields(params, ("yield", "mix_water", "dead_vol", "total_sacks", "cmt_sg"),
                              f"cement_params.{name}", nullable=("dead_vol",) if name == "Main" else ())
    for name, params in data.get("lab_qc_params", {}).items():
        _check_numeric_fields(params, ("api_fl", "free_water", "bhct", "free_water_45", "surface_hardened_hours"), f"lab_qc_params.{name}",
                              nullable=("free_water_45", "surface_hardened_hours", "bhct") if name == "Main" else ("free_water_45", "surface_hardened_hours"))
    hardware_columns = {"Description", "MD (m)", "Size (in)", "ID (in)",
                        "Joint (m)", "Weight (ppf)", "Grade", "Collapse (psi)", "Burst (psi)"}
    for key in ("hardware_table", "hardware_editor_draft"):
        hardware = data.get(key)
        if hardware is not None and not hardware_columns.issubset(hardware.columns):
            raise ValueError(f"{key} is missing required columns.")


# F-03 (system audit 2026-09-29, owner-approved): the Phase VII lab grid is
# rendered with st.column_config.TextColumn editors (phase_7_lab), which
# reject non-string underlying dtypes with a raw StreamlitAPIException
# ("The configured column type 'text' for column 'Concentration' is not
# compatible for editing the underlying data type 'ColumnDataKind.FLOAT'").
# The app's own save path always writes strings into these columns, but a
# hand-edited or migrated project JSON can carry numeric cells (e.g.
# Concentration: 100.0); decode used to accept it and Phase VII crashed on
# first render. Coerce every text-valued grid column to strings at decode
# time — before any session write — while keeping missing cells (null/NaN)
# missing instead of fabricating "None"/"nan" text. Unit is a
# SelectboxColumn whose options are strings, so a non-string dtype there is
# equally foreign to the editor and gets the same treatment.
_LAB_GRID_TEXT_COLUMNS = ("Material", "Concentration", "Unit", "Mass", "Lot No")


def _is_missing_cell(cell):
    return cell is None or cell is pd.NA or (isinstance(cell, float) and math.isnan(cell))


def _coerce_text_columns(df, columns):
    if not isinstance(df, pd.DataFrame):
        return df
    for column in columns:
        if column not in df.columns:
            continue
        series = df[column]
        already_text = series.dtype == object and all(
            isinstance(cell, (str, type(None))) or _is_missing_cell(cell)
            for cell in series)
        if already_text:
            continue
        df[column] = pd.Series([cell if _is_missing_cell(cell) else str(cell)
                                for cell in series], index=series.index, dtype=object)
    return df


def _normalize_lab_grids(project):
    """F-03: decode-time dtype normalization for every lab grid the session
    will ever render — the active lab_grid_dfs AND the archived inactive-
    slurry drafts, which the enable-cycle later restores into lab_grid_dfs
    and would otherwise re-introduce the same crash after the load."""
    for grid in project.get("lab_grid_dfs", {}).values():
        _coerce_text_columns(grid, _LAB_GRID_TEXT_COLUMNS)
    for draft in project.get("inactive_slurry_drafts", {}).values():
        if isinstance(draft, dict):
            _coerce_text_columns(draft.get("lab_grid_dfs"), _LAB_GRID_TEXT_COLUMNS)
    return project


def normalize_hardware_text_columns(df):
    """Normalize accepted numeric depths/sizes without inventing missing cells."""
    return _coerce_text_columns(df, ("MD (m)", "Size (in)"))


def decode_project(raw_bytes, deserialize_item):
    """All parsing, reconstruction and shape checks occur without session writes."""
    loaded = json.loads(raw_bytes.decode("utf-8-sig"),
                        parse_constant=_reject_constant, object_pairs_hook=_unique_keys)
    if not isinstance(loaded, dict):
        raise ValueError("Project JSON must contain an object of project fields.")
    if any(not isinstance(k, str) for k in loaded):
        raise ValueError("Project field names must be strings.")
    project = {key: deserialize_item(value) for key, value in loaded.items() if is_project_key(key)}
    _check_finite(project)
    _normalize_lab_grids(project)
    _validate_project(project)
    restore_canonical_fields(project)
    _validate_project(project)
    for key in ("hardware_table", "hardware_editor_draft"):
        normalize_hardware_text_columns(project.get(key))
    return project


def replace_project_state(state, project, signature, preserved_keys=()):
    """Commit the prepared state, restoring the original on any write failure."""
    previous = dict(state.items())
    preserved = {key: previous[key] for key in preserved_keys if key in previous}
    try:
        for key in list(state):
            if key not in preserved:
                del state[key]
        for key, value in project.items():
            state[key] = value
        state["last_loaded_hash"] = signature
        # The navigation radio was already mounted during this run. Its old
        # browser selection can remain checked after session replacement even
        # though the next run renders Phase I from the cleared widget state.
        state["_reset_navigation_to_phase1"] = True
    except Exception:
        for key in list(state):
            if key not in preserved:
                del state[key]
        for key, value in previous.items():
            if key not in preserved:
                state[key] = value
        raise
