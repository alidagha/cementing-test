"""Phase IX inputs and transient execution. Word readiness is advisory in 9F."""
from copy import deepcopy
import math
from uuid import uuid4

import pandas as pd
import streamlit as st

import centralizer_adapter as adapter
import materials_db
import rheology
from cement_chart_model import resolve_cement_placement, resolve_chart_geometry
from project_state import fingerprint


AUX_FLUIDS = ("Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind")
DENSITIES = tuple(f"{p}/{q}" for p, q in adapter.centralizer_engine._DENSITY_LADDER)
PHYSICS_HELP = (
    "Static Parity: Uses the final displacement fluid columns with hydrostatic/buoyancy effects. "
    "Circulation-induced annular friction and axial drag are not applied.\n\n"
    "Dynamic Circulating: Adds pump-rate- and Bingham-rheology-dependent annular friction and axial drag "
    "(API RP 13D) to the hydrostatic state. Requires a valid displacement pump rate and complete rheology "
    "for every active fluid."
)
ZONE_FIELDS = {"top_md", "bottom_md", "density", "target_standoff_pct", "product_nr", "custom_product_id"}


def new_config():
    return {"version": 1, "placement_mode": "optimize", "physics_mode": "static",
            "zones": [], "custom_products": [], "aux_rheology": {}}


def validate_config(config):
    """Current input schema only; incomplete numeric/selection drafts may reopen."""
    if not isinstance(config, dict) or set(config) != set(new_config()):
        raise ValueError("centralizer_config requires only the current version-1 input fields.")
    if type(config["version"]) is not int or config["version"] != 1:
        raise ValueError("centralizer_config.version must be 1.")
    if config["placement_mode"] not in ("direct", "optimize") or config["physics_mode"] not in ("static", "dynamic"):
        raise ValueError("Centralizer placement/physics modes are invalid.")
    if not isinstance(config["zones"], list):
        raise ValueError("Centralizer zones must be a list of draft records.")
    for zone in config["zones"]:
        if not isinstance(zone, dict) or set(zone) - ZONE_FIELDS:
            raise ValueError("Centralizer zone contains invalid draft fields.")
        for field in ("top_md", "bottom_md", "target_standoff_pct"):
            value = zone.get(field)
            if value is not None:
                adapter._number(value, f"Centralizer zone {field}")
        if zone.get("density") is not None and zone["density"] not in DENSITIES:
            raise ValueError("Centralizer Design Density must use the certified ladder.")
        if zone.get("product_nr") is not None:
            adapter._nr({"nr": zone["product_nr"]})
        if zone.get("custom_product_id") is not None and (
                not isinstance(zone["custom_product_id"], str) or not zone["custom_product_id"].strip()):
            raise ValueError("Centralizer custom_product_id must be nonblank text or null.")
    if not isinstance(config["custom_products"], list):
        raise ValueError("Custom Centralizers must be a saved product list.")
    adapter.validate_custom_products(config["custom_products"])
    aux = config["aux_rheology"]
    if not isinstance(aux, dict) or set(aux) - set(AUX_FLUIDS):
        raise ValueError("Centralizer auxiliary rheology must contain auxiliary fluid records only.")
    for fluid, readings in aux.items():
        if not isinstance(readings, dict) or set(readings) - {str(rpm) for rpm in rheology.RPM_ORDER}:
            raise ValueError(f"{fluid}: auxiliary rheology may contain only the seven RPM inputs.")
        for value in readings.values():
            if value is not None:
                adapter._number(value, f"{fluid} RPM reading")


def product_candidates(products, custom_products, pipe_size_in):
    """One candidate list; identity is explicit and Hole Size never filters it."""
    adapter.validate_custom_products(custom_products)
    size = adapter._positive_pipe_size(pipe_size_in)
    return ([{"product_nr": p["nr"], "custom_product_id": None, "product": p}
             for p in adapter.filter_official_products(products, size)] +
            [{"product_nr": None, "custom_product_id": p["custom_id"], "product": p}
             for p in custom_products if p["pipe_size_in"] == size])


def product_view(candidate):
    product = candidate["product"]
    prefix = "[Custom] " if candidate["custom_product_id"] is not None else ""
    return {"Identification": prefix + product["identification"], "Hole Size (in)": product["hole_size_in"],
            "Kind": product["kind"], "Restoring Force (lbf)": product.get("restoring_force_lbf")}


def save_custom_product(state, draft, *, custom_id=None):
    """Validate before committing; allocate an opaque identity once on first Save."""
    config = state["centralizer_config"]
    saved = config["custom_products"]
    if custom_id is None and len(saved) >= 5:
        raise ValueError("A project may save at most five Custom Centralizers.")
    if custom_id is not None and sum(p["custom_id"] == custom_id for p in saved) != 1:
        raise ValueError("Select an existing Custom Centralizer before editing it.")
    record = {**deepcopy(draft), "custom_id": custom_id or "unsaved-draft"}
    adapter.to_engine_custom_product(record)
    if custom_id is None:
        record["custom_id"] = uuid4().hex
    replacement = [record if p["custom_id"] == custom_id else p for p in saved]
    if custom_id is None:
        replacement.append(record)
    adapter.validate_custom_products(replacement)
    config["custom_products"] = replacement
    return record


def delete_custom_product(state, custom_id):
    """Keep selected zone references unresolved; never redirect a deleted identity."""
    products = state["centralizer_config"]["custom_products"]
    if sum(p["custom_id"] == custom_id for p in products) != 1:
        raise ValueError("Custom Centralizer to delete is missing or ambiguous.")
    state["centralizer_config"]["custom_products"] = [p for p in products if p["custom_id"] != custom_id]


def auto_populate(state):
    """Explicit helper only: engineering TOC, never report-only Top/Bottom."""
    geometry = adapter.to_engine_geometry(state)
    if geometry is None:
        raise ValueError("Centralizer zones are not applicable to this job.")
    bounds = geometry["wellbore"]
    top, previous, shoe = (bounds[key] for key in ("string_top", "prev_shoe_depth", "string_shoe"))
    cement = resolve_cement_placement(state)
    toc = min(row["top_md"] for row in cement)
    if not all(math.isfinite(value) for value in (top, toc, previous, shoe)) or not top <= toc <= previous <= shoe:
        raise ValueError("Auto-Populate requires active Top <= calculated TOC <= Previous Shoe <= String Shoe. "
                         "Review geometry/volumes or enter explicit manual zones; current zones are unchanged.")
    zones = []
    for start, end, density, target in ((top, toc, "1/4", 67.), (toc, previous, "1/3", 70.),
                                      (previous, shoe, "1/1", 75.)):
        start, end = max(start, top), min(end, shoe)
        if start < end:
            zones.append({"top_md": start, "bottom_md": end, "density": density,
                          "target_standoff_pct": target, "product_nr": None, "custom_product_id": None})
    return zones


def source_signature(state, products=None):
    """Pure fingerprint of sources consumed by the selected solver; no solver call."""
    config = state.get("centralizer_config")
    validate_config(config)
    products = adapter.load_official_catalog() if products is None else products
    geometry = adapter.to_engine_geometry(state)
    snapshot = adapter.build_fluid_snapshot(state)
    if geometry is None:
        raise ValueError("Centralizer is not applicable to this job.")
    selected_custom = {zone.get("custom_product_id") for zone in config["zones"]
                       if zone.get("custom_product_id") is not None}
    mapped = [adapter.resolve_zone_product(zone, products, config["custom_products"]) for zone in config["zones"]]
    cfg = state.get("fluids_config", {})
    active = cfg.get("active", [])
    sources = {name: cfg.get("params", {}).get(name, state.get("fluid_data", {}).get(name, {})) for name in active}
    body = {"job": state.get("job_type"), "geometry": geometry,
            "measured_hardware": state["hardware_table"].reindex(columns=[
                "Description", "MD (m)", "Size (in)", "ID (in)"]),
            "geometry_selection": {key: state.get("placement_config", {}).get(key)
                                   for key in ("target_row", "host_row", "tie_back_liner_lap_m")},
            "snapshot": snapshot, "placement_mode": config["placement_mode"], "physics_mode": config["physics_mode"],
            "zones": config["zones"], "products": mapped,
            "custom_products": {p["custom_id"]:p for p in config["custom_products"] if p["custom_id"] in selected_custom},
            "fluids": {name: {"volume": source.get("volume"),
                               **({"density": source.get("density")} if name != "Displacement Fluid" else {})}
                       for name, source in sources.items() if name != "Spacer Behind"}}
    if config["physics_mode"] == "dynamic":
        adapter.require_dynamic_geometry(state)
        body["dynamic"] = {
            "active": sorted(active), "pump_rate": sources.get("Displacement Fluid", {}).get("pump_rate"),
            "mud": {field: state.get(field, state.get("well_data", {}).get(field))
                    for field in ("plastic_viscosity", "yield_point")},
            "lab": {name: (adapter.spacer_bhct_down(state)["source"] if name == "Spacer" else
                           {key: state.get("lab_qc_params", {}).get(name, {}).get("rheology", {}).get("bhct_down", {}).get(key)
                            for key in ("selected", "readings")})
                    for name in active if name == "Spacer" or (name in materials_db.PHASE7_LAB_FLUIDS and name != "Pre Flush")},
            "aux": {name: ({key: rheology._numeric(value) for key, value in adapter.preflush_readings(state).items()}
                           if isinstance(adapter.preflush_readings(state), dict) else adapter.preflush_readings(state))
                    if name == "Pre Flush" else config["aux_rheology"].get(name)
                    for name in active if name in AUX_FLUIDS and name != "Spacer"},
        }
    return fingerprint(body)


def result_is_current(state, products=None):
    if state.get("_centralizer_result") is None or not state.get("_centralizer_signature"):
        return False
    try:
        return state["_centralizer_signature"] == source_signature(state, products)
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return False


def execute(state, products=None):
    """The only execution action; failed attempts retire any old successful result."""
    state.pop("_centralizer_result", None)
    state.pop("_centralizer_signature", None)
    state.pop("_centralizer_error", None)
    if not adapter.centralizer_applicable(state.get("job_type")):
        return None
    try:
        config = state.get("centralizer_config")
        validate_config(config)
        products = adapter.load_official_catalog() if products is None else products
        signature = source_signature(state, products)
        args = dict(mode=config["placement_mode"], custom_products=config["custom_products"])
        if config["physics_mode"] == "dynamic":
            result = adapter.solve_dynamic(state, config["zones"], products, aux_rheology=config["aux_rheology"], **args)
        else:
            result = adapter.solve_static(state, config["zones"], products, **args)
        state["_centralizer_result"] = result
        state["_centralizer_signature"] = signature
        return result
    except (ValueError, TypeError, KeyError, OverflowError, OSError) as exc:
        state["_centralizer_error"] = str(exc)
        raise ValueError(str(exc)) from None


def _commit(field, key, index=None, fluid=None, rpm=None, epoch=None):
    """Commit shadow values before navigation unmounts the widget."""
    if key not in st.session_state:
        return
    if index is not None and epoch is not None and epoch != st.session_state.get("_centralizer_zone_epoch", 0):
        return  # Add/delete/Auto-Populate retired this zone's widget generation.
    config = st.session_state["centralizer_config"]
    value = st.session_state[key]
    if fluid is not None:
        config["aux_rheology"].setdefault(fluid, {})[str(rpm)] = value
    elif index is not None and index < len(config["zones"]):
        if field == "product":
            zone = config["zones"][index]
            zone.update(product_nr=None, custom_product_id=None)
            if value is not None:
                source, identity = value.split(":", 1)
                zone["product_nr" if source == "official" else "custom_product_id"] = int(identity) if source == "official" else identity
        else:
            config["zones"][index][field] = value
    elif index is None:
        config[field] = value
    st.session_state.pop("_centralizer_error", None)


def _zones_action(action, index=None):
    config = st.session_state["centralizer_config"]
    try:
        if action == "auto":
            config["zones"] = auto_populate(st.session_state)
        elif action == "add":
            config["zones"].append({"top_md": None, "bottom_md": None, "density": "1/4",
                                    "target_standoff_pct": 67., "product_nr": None, "custom_product_id": None})
        elif action == "delete":
            del config["zones"][index]
        st.session_state["_centralizer_zone_epoch"] = st.session_state.get("_centralizer_zone_epoch", 0) + 1
        st.session_state.pop("_centralizer_error", None)
    except ValueError as exc:
        st.session_state["_centralizer_error"] = str(exc)


def _render_custom_manager(config):
    with st.expander("Project Custom Centralizers (maximum 5)"):
        saved = {p["custom_id"]: p for p in config["custom_products"]}
        st.caption(f"{len(saved)} of 5 Custom Centralizers saved.")
        choice = st.selectbox("Custom product to manage", [None, *saved],
            format_func=lambda value: "Add new Custom Centralizer" if value is None else f"{saved[value]['identification']} [{value}]",
            key="_centralizer_custom_choice")
        record = saved.get(choice, {})
        revision = fingerprint([choice, record])[:16]
        with st.form(f"_centralizer_custom_form_{revision}"):
            draft = {}
            for field, label in (("identification", "Identification"), ("manufacturer", "Manufacturer"), ("description", "Description")):
                draft[field] = st.text_input(label, value=record.get(field, ""), key=f"_centralizer_custom_{revision}_{field}")
            draft["kind"] = st.selectbox("Kind", ["rigid", "spring"],
                index=["rigid", "spring"].index(record["kind"]) if record.get("kind") is not None else None,
                key=f"_centralizer_custom_{revision}_kind")
            for field, label in (("pipe_size_in", "Pipe Size (in)"), ("hole_size_in", "Hole Size (in)"),
                    ("max_od_in", "Max OD (in)"), ("min_od_in", "Min OD (in)"),
                    ("starting_force_lbf", "Starting Force (lbf)"), ("running_force_lbf", "Running Force (lbf)"),
                    ("restoring_force_lbf", "Restoring Force (lbf)")):
                draft[field] = st.number_input(label, min_value=0., value=record.get(field),
                                               key=f"_centralizer_custom_{revision}_{field}")
            draft["bows"] = st.number_input("Bows", min_value=0, step=1, value=record.get("bows"),
                                             key=f"_centralizer_custom_{revision}_bows")
            if st.form_submit_button("Save / Apply Custom Centralizer"):
                try:
                    save_custom_product(st.session_state, draft, custom_id=choice)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if choice is not None and st.button("Delete Custom Centralizer", key="_centralizer_delete_custom"):
            delete_custom_product(st.session_state, choice)
            st.session_state.pop("_centralizer_custom_choice", None)
            st.rerun()


def _render_zones(config, candidates):
    options = {}
    for candidate in candidates:
        token = (f"official:{candidate['product_nr']}" if candidate["product_nr"] is not None
                 else f"custom:{candidate['custom_product_id']}")
        view = product_view(candidate)
        # Selection labels carry the stable identity to disambiguate duplicate Identifications.
        options[token] = (f"{view['Identification']} | {view['Hole Size (in)']} in | {view['Kind']} | "
                          f"{view['Restoring Force (lbf)']} lbf [{token}]")
    epoch = st.session_state.get("_centralizer_zone_epoch", 0)
    for index, zone in enumerate(config["zones"]):
        st.markdown(f"**Zone {index + 1}**")
        prefix = f"_centralizer_zone_{epoch}_{index}"
        columns = st.columns(4)
        for column, field, label in ((columns[0], "top_md", "Top MD (m)"), (columns[1], "bottom_md", "Bottom MD (m)"),
                                    (columns[3], "target_standoff_pct", "Target Standoff (%)")):
            key = f"{prefix}_{field}"
            st.session_state[key] = zone.get(field)
            column.number_input(f"{label} — Zone {index + 1}", min_value=0.,
                **({"max_value":100.} if field == "target_standoff_pct" else {}),
                value=None, key=key, on_change=_commit, args=(field, key, index),
                kwargs={"epoch":epoch},
                help="Target must be greater than zero and at most 100%." if field == "target_standoff_pct" else None)
        key = f"{prefix}_density"
        st.session_state[key] = zone.get("density")
        columns[2].selectbox(f"Design Density — Zone {index + 1}", DENSITIES, index=None, key=key,
                            on_change=_commit, args=("density", key, index), kwargs={"epoch":epoch})
        selected = (f"official:{zone['product_nr']}" if zone.get("product_nr") is not None
                    else f"custom:{zone['custom_product_id']}" if zone.get("custom_product_id") is not None else None)
        choices = dict(options)
        if selected is not None and selected not in choices:
            choices[selected] = f"Unavailable in current candidates: {selected}; reselect a product"
            st.warning(f"Zone {index + 1}: saved product is not in the current pipe-size candidate list.")
        key = f"{prefix}_product"
        st.session_state[key] = selected
        st.selectbox(f"Product — Zone {index + 1}", [None, *choices], key=key,
            format_func=lambda token, choices=choices: "Select an Official or Custom product" if token is None else choices[token],
            on_change=_commit, args=("product", key, index), kwargs={"epoch":epoch})
        candidate = next((p for p in candidates if p["product_nr"] == zone.get("product_nr")
                          and p["custom_product_id"] == zone.get("custom_product_id")), None)
        if candidate is not None:
            with st.expander(f"More Information — Zone {index + 1}"):
                p = candidate["product"]
                st.write({label:p[field] for label,field in (("Manufacturer","manufacturer"),
                    ("Starting Force (lbf)","starting_force_lbf"), ("Running Force (lbf)","running_force_lbf"),
                    ("Max OD (in)","max_od_in"), ("Min OD (in)","min_od_in"))})
        st.button(f"Delete Zone {index + 1}", key=f"{prefix}_delete", on_click=_zones_action, args=("delete", index))
    st.button("Add Zone", key="_centralizer_add_zone", on_click=_zones_action, args=("add",))
    st.button("Auto-Populate Zones", key="_centralizer_auto_zones", on_click=_zones_action, args=("auto",),
              help="Uses calculated cement TOC and resolved string bounds. Products remain unselected.")


def render():
    st.header("Phase IX: Centralizer")
    job = st.session_state.get("job_type")
    if job in ("CMT PLUG", "CMT SQUEEZE", materials_db.CT_JOB):
        st.info("Not applicable: Centralizer calculation is not required for Plug or Squeeze.")
        return
    if job in adapter.SHALLOW_CASING_JOBS:
        st.info("Not applicable: Centralizer calculation is not required for this shallow casing job.")
        return
    if not adapter.centralizer_applicable(job):
        st.warning("Select a supported Casing, Liner or Tie Back job in Phase I.")
        return
    config = st.session_state.setdefault("centralizer_config", new_config())
    try:
        validate_config(config)
        products = adapter.load_official_catalog()
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        return
    for field, label, options, labels, key in (
        ("placement_mode", "Placement", ["direct", "optimize"], {"direct":"Direct Check", "optimize":"Optimize"}, "_centralizer_placement"),
        ("physics_mode", "Physics", ["static", "dynamic"], {"static":"Static Parity", "dynamic":"Dynamic Circulating"}, "_centralizer_physics")):
        st.session_state[key] = config[field]
        st.radio(label, options, format_func=labels.get, key=key, horizontal=True,
                 help=PHYSICS_HELP if field == "physics_mode" else "Direct evaluates the entered density. Optimize uses the certified engine density ladder.",
                 on_change=_commit, args=(field, key))
    _render_custom_manager(config)
    try:
        geometry = adapter.to_engine_geometry(st.session_state)
        st.caption(f"Active Centralizer string: {geometry['wellbore']['string_top']:g}–{geometry['wellbore']['string_shoe']:g} m MD")
        description = {"casing":"Casing", "liner":"Liner", "tieback":"Tie Back"}[geometry["job_type"]]
        pipe_size = next(segment["od_in"] for segment in resolve_chart_geometry(st.session_state)["active_string"]
                         if segment["description"] == description)
        candidates = product_candidates(products, config["custom_products"], pipe_size)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        candidates = []
        st.warning(f"Complete current geometry in Phase II/III: {exc}")
    _render_zones(config, candidates)
    if config["physics_mode"] == "dynamic":
        st.caption("Mud PV/YP: Phase II. Cement/Scavenger/Diesel/Spacer/Pre Flush: Phase VII BHCT — Ramp-Down. Pump rate: Phase IV Displacement Fluid.")
        for fluid in AUX_FLUIDS:
            if fluid in ("Spacer", "Pre Flush") or fluid not in st.session_state.get("fluids_config", {}).get("active", []):
                continue
            st.markdown(f"**{fluid} Bingham rheology**")
            readings = config["aux_rheology"].get(fluid, {})
            for column, rpm in zip(st.columns(7), rheology.RPM_ORDER):
                key = f"_centralizer_aux_{fluid}_{rpm}"
                st.session_state[key] = readings.get(str(rpm))
                column.number_input(f"{rpm} RPM — {fluid}", min_value=0., value=None, key=key,
                                    on_change=_commit, args=("readings", key, None, fluid, rpm))
            try:
                fit = adapter._dynamic_fann(readings, fluid)
                st.caption(f"PV = {fit['pv_cp']:g} cP; Ty = {fit['ty_lbf_100ft2']:g} lbf/100ft²; IOD = {fit['iod']:g}")
            except ValueError:
                st.caption("Complete all seven RPM readings; derived PV/Ty/IOD will appear here.")
    if st.button("Execute Centralizer", type="primary", key="_centralizer_execute"):
        try:
            with st.spinner("Calculating Centralizer..."):
                execute(st.session_state, products)
        except ValueError:
            pass  # Controlled error is displayed below; no old result remains current.
    if st.session_state.get("_centralizer_error"):
        st.error(st.session_state["_centralizer_error"])
    if result_is_current(st.session_state, products):
        result = st.session_state["_centralizer_result"]
        st.success("Current Centralizer calculation complete.")
        st.dataframe(pd.DataFrame([{"Zone #":index + 1, "Computed Density":row["density_computed"],
                                   "Min Standoff (%)":row["min_stdf"] * 100,
                                   "Status":"Pass" if row["meets_target"] else "Target missed"}
                                  for index,row in enumerate(result["zones"])]), hide_index=True)
        if any(not row["meets_target"] for row in result["zones"]):
            st.warning("Required target standoff was not achieved in one or more zones. The calculation is valid.")
    else:
        st.info("Needs Review: Execute the current Centralizer design. Saved projects require a fresh execution after load.")
