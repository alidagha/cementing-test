"""Explicit current Phase-IX prerequisite for tests of unrelated Word behavior."""
from copy import deepcopy
import centralizer_adapter as adapter
import phase_9_centralizer as phase9
from cement_chart_model import resolve_chart_geometry


def execute_centralizer(state, *, zones=2, physics="static", mode="direct", custom=False, target=70.):
    original = state
    state = state.to_dict() if hasattr(state, "to_dict") else state
    if not adapter.centralizer_applicable(state.get("job_type")):
        return None
    geometry = adapter.to_engine_geometry(state)
    resolved = resolve_chart_geometry(state)
    description = {"casing":"Casing", "liner":"Liner", "tieback":"Tie Back"}[geometry["job_type"]]
    pipe = next(s["od_in"] for s in resolved["active_string"] if s["description"] == description)
    catalog = adapter.load_official_catalog()
    candidates = [p for p in adapter.filter_official_products(catalog, pipe) if p["kind"] == "rigid"]
    config = phase9.new_config()
    config['aux_rheology'] = deepcopy(state.get('centralizer_config', {}).get('aux_rheology', {}))
    config.update(placement_mode=mode, physics_mode=physics)
    nr, custom_id = None, None
    if custom or not candidates:
        custom_id = "explicit-word-fixture-product"
        hole = geometry["wellbore"]["hole_size"] / adapter.INCH_TO_M
        config["custom_products"] = [dict(custom_id=custom_id, identification="Word Fixture",
            manufacturer="Test Owner", description="Explicit project-owned fixture",
            pipe_size_in=pipe, hole_size_in=hole, kind="rigid", bows=0, max_od_in=hole,
            min_od_in=hole, starting_force_lbf=0., running_force_lbf=0., restoring_force_lbf=0.)]
    else:
        nr = candidates[0]["nr"]
    top, bottom = geometry["wellbore"]["string_top"], geometry["wellbore"]["string_shoe"]
    config["zones"] = [dict(top_md=top+(bottom-top)*i/zones, bottom_md=top+(bottom-top)*(i+1)/zones,
        density="1/3", target_standoff_pct=target, product_nr=nr, custom_product_id=custom_id)
        for i in range(zones)]
    state["centralizer_config"] = config
    result = phase9.execute(state, catalog)
    if state is not original:
        _copy_execution(state, original)
    return result


def ensure_current_centralizer(state):
    """Explicit fresh design for unrelated export fixtures after an upstream edit/restore."""
    original = state
    state = state.to_dict() if hasattr(state, "to_dict") else state
    if adapter.centralizer_applicable(state.get("job_type")) and not phase9.result_is_current(state):
        execute_centralizer(state)
        if state is not original:
            _copy_execution(state, original)


def _copy_execution(calculated, state):
    for key in ("centralizer_config", "_centralizer_result", "_centralizer_signature", "_centralizer_error"):
        if key in calculated:
            state[key] = calculated[key]
        elif key in state:
            del state[key]
