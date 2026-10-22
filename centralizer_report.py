"""Current-result presentation bridge; physics remains in the certified adapter/engine."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

import materials_db
import centralizer_adapter as adapter
from phase_9_centralizer import result_is_current


NOTE_BODY = "Recommended Centralizer Performance Data is Based on API 10D Specifications."
WARNING = ("WARNING: Required minimum standoff was not achieved in one or more centralizer zones. "
           "Refer to the placement results above.")
NOT_APPLICABLE = "Not applicable (Plug/Squeeze)."
# The byte-frozen Companion uses pyplot. Serialize its render calls only;
# all report inputs and temporary directories remain independent.
_RENDER_LOCK = Lock()


def _companion():
    try:
        import cement_charts_engine
    except ImportError as exc:
        raise ValueError("Centralizer Word presentation requires the certified Companion and Matplotlib.") from exc
    return cement_charts_engine


def prepare_report(state):
    """Pure projection of a current executed result into the Companion's accepted contract."""
    job = state.get("job_type")
    if job in ("CMT PLUG", "CMT SQUEEZE", materials_db.CT_JOB):
        return {"applicable": False, "analysis": None, "view": None, "source": None, "warning": False}
    if not adapter.centralizer_applicable(job) or not result_is_current(state):
        raise ValueError("Phase IX: Execute a current successful Centralizer calculation before Word export.")
    result = state["_centralizer_result"]
    if (not isinstance(result, dict) or result.get("mode") not in ("direct", "optimize") or
            not isinstance(result.get("profile"), dict) or not isinstance(result.get("zones"), list)
            or not result["zones"]):
        raise ValueError("Phase IX: A completed Centralizer result is required before Word export.")
    geometry = adapter.to_engine_geometry(state)
    config = state["centralizer_config"]
    catalog = adapter.load_official_catalog()
    products = {}
    for zone in result["zones"]:
        mapped = adapter.resolve_zone_product(zone, catalog, config["custom_products"])
        if zone.get("product_name") != mapped["name"] or type(zone.get("count")) is not int or zone["count"] < 0:
            raise ValueError("Phase IX: Current zone product/count diagnostics are incomplete.")
        if type(zone.get("meets_target")) is not bool:
            raise ValueError("Phase IX: Current zone target diagnostics are incomplete.")
        products[mapped["name"]] = mapped
    analysis = deepcopy(result["profile"])
    if not analysis.get("centralizer_md") or not analysis.get("zones_min"):
        raise ValueError("Phase IX: The current result carries no completed Pipe Standoff profile.")
    analysis.update(zones=deepcopy(result["zones"]), products=list(products.values()),
                    wellbore=geometry["wellbore"], job_type=geometry["job_type"],
                    well_name=state.get("well_name", ""))
    view = _companion().build_view(analysis)
    if view["n_rigid"] is None or view["n_spring"] is None or view["n_rigid"] + view["n_spring"] != view["n_cent"]:
        raise ValueError("Phase IX: Exact Rigid/Spring zone counts must account for all current Centralizers.")
    return {"applicable": True, "analysis": analysis, "view": view,
            "source": state["_centralizer_signature"],
            "warning": any(not zone["meets_target"] for zone in result["zones"])}


def render_chart_png(prepared):
    """Call the frozen renderer once, then discard its isolated temporary PNG."""
    if not prepared["applicable"]:
        raise ValueError("Pipe Standoff is not applicable to Plug/Squeeze.")
    companion = _companion()
    with _RENDER_LOCK, TemporaryDirectory(prefix="round9g-standoff-") as directory:
        before = set(companion.plt.get_fignums())
        try:
            path = Path(directory) / "pipe-standoff.png"
            companion.render_pipe_standoff_chart(deepcopy(prepared["analysis"]), str(path), dpi=300)
            return path.read_bytes()
        finally:
            for number in set(companion.plt.get_fignums()) - before:
                companion.plt.close(number)
