"""Passive pytest instrumentation, loaded only by the dedicated diagnostic job.

The optional completion timeout affects Build clicks in these four methods only.
It does not change tests, non-Build reruns, assertions, inputs or solver settings.
"""
from copy import deepcopy
from functools import wraps
from io import BytesIO
from pathlib import Path
import hashlib
import inspect
import json
import os
import resource
import threading
import time

from docx import Document
from docx.document import Document as DocxDocument
from docxtpl import DocxTemplate
from matplotlib.figure import Figure
from streamlit.runtime.scriptrunner import get_script_run_ctx, script_runner
from streamlit.testing.v1 import AppTest
import phase_10_procedure as report
import project_state
import pumping_simulation as pumping

OUT = Path(os.environ["DIAG_DIR"])
BY_STATE, RECORDS, SOLVERS, NODE = {}, [], [], ""
LOCAL = threading.local()


def snapshot():
    paths = ("/proc/self/status", "/proc/loadavg", "/sys/fs/cgroup/cpu.stat",
             "/sys/fs/cgroup/cpu.pressure", "/sys/fs/cgroup/memory.current")
    return {"process_cpu": time.process_time(), "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            **{p: Path(p).read_text() for p in paths if Path(p).exists()}}


def current():
    context = get_script_run_ctx(suppress_warning=True)
    return BY_STATE.get(id(context.session_state._state)) if context else None


def stage(function, name):
    @wraps(function)
    def measured(*args, **kwargs):
        entry = current()
        solver = None
        if name == "frozen_build_three_charts":
            solver = {"build": entry["id"] if entry else None, "test": NODE,
                      "started": time.monotonic(), "completed": False}
            SOLVERS.append(solver)
        if entry is None:
            start = time.perf_counter()
            try:
                result = function(*args, **kwargs)
                if solver is not None:
                    solver["completed"] = True
                return result
            finally:
                if solver is not None:
                    solver["seconds"] = time.perf_counter() - start
        stack = getattr(LOCAL, "stack", [])
        event = {"name": name, "parent": stack[-1] if stack else None,
                 "start_seconds": time.perf_counter() - entry["_start"]}
        stack.append(name)
        LOCAL.stack = stack
        entry["_active"] = stack
        start, cpu = time.perf_counter(), time.thread_time()
        entry["stage_calls"][name] = entry["stage_calls"].get(name, 0) + 1
        if name == "frozen_simulate":
            job = args[0]
            entry["pumping_sequence"] = [vars(s).copy() for s in job.placement]
            entry["total_pumped_bbl"] = sum(s.volume_bbl for s in job.placement)
            entry["options"] = {k: getattr(job, k) for k in ("dt_min", "tail_cap_min", "shutin_ramp_min")}
        try:
            result = function(*args, **kwargs)
            if solver is not None:
                solver["completed"] = True
                entry["_figure"], entry["_result"] = result[:2]
            return result
        except BaseException as exc:
            event["exception"] = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            event.update(seconds=time.perf_counter() - start, cpu_seconds=time.thread_time() - cpu)
            entry["stages"].append(event)
            stack.pop()
            if solver is not None:
                solver["seconds"] = event["seconds"]
    return measured


prepare = stage(project_state.prepare_calculations, "prepare_calculations")
project_state.prepare_calculations = report.prepare_calculations = prepare
report.build_master_context = stage(report.build_master_context, "build_master_context")
report.postprocess_well_report = stage(report.postprocess_well_report, "postprocess_well_report")
pumping.prepare_pumping_simulation = stage(pumping.prepare_pumping_simulation, "pumping_preflight")
pumping.run_pumping_simulation = stage(pumping.run_pumping_simulation, "run_pumping_simulation")
pumping.fcm.build_three_charts = stage(pumping.fcm.build_three_charts, "frozen_build_three_charts")
pumping.fcm.simulate = stage(pumping.fcm.simulate, "frozen_simulate")
pumping.fcm.render_three_charts = stage(pumping.fcm.render_three_charts, "frozen_render_three_charts")
for method in ("__init__", "render", "save"):
    setattr(DocxTemplate, method, stage(getattr(DocxTemplate, method), "DocxTemplate." + method))
DocxDocument.save = stage(DocxDocument.save, "docx_save")
original_savefig = Figure.savefig


@wraps(original_savefig)
def savefig(self, *args, **kwargs):
    entry = current()
    name = "pumping_png" if entry and entry.get("_figure") is self else "other_chart_png"
    return stage(original_savefig, name)(self, *args, **kwargs)


Figure.savefig = savefig
original_cleanup = script_runner._clean_problem_modules


def owned_open(figure):
    # Compare object identity, since pyplot can reuse an integer figure number.
    from matplotlib._pylab_helpers import Gcf
    return any(manager.canvas.figure is figure for manager in Gcf.get_all_fig_managers())


@wraps(original_cleanup)
def cleanup():
    entry = current()
    if entry and entry.get("_figure") is not None:
        entry["owned_closed_before_native_cleanup"] = not owned_open(entry["_figure"])
    return original_cleanup()


script_runner._clean_problem_modules = cleanup


def inspect_doc(data):
    doc = Document(BytesIO(data))
    body = list(doc._element.body)
    def drawing(description):
        return [p for p in doc.paragraphs if p._p.xpath('.//wp:docPr[@descr="' + description + '"]')]
    pump = drawing("Pumping Simulation Charts")
    diagnostic = drawing("Static Well Security and Fluid Sequence")
    central = drawing("Pipe Standoff")
    iv = [p for p in doc.paragraphs if p.text.strip() == "IV. Fluids Sequence"]
    v = [p for p in doc.paragraphs if p.text.strip() == "V. Cementing Program"]
    ordered = (len(pump) == len(diagnostic) == len(iv) == len(v) == 1 and
               body.index(iv[0]._p) < body.index(diagnostic[0]._p) < body.index(pump[0]._p) < body.index(v[0]._p))
    png = None
    if pump:
        rid = pump[0]._p.xpath('.//a:blip/@r:embed')[0]
        png = hashlib.sha256(doc.part.related_parts[rid].blob).hexdigest()
    return {"pumping_images": len(pump), "diagnostic_images": len(diagnostic),
            "centralizer_images": len(central), "iv_order": ordered,
            "placeholder_absent": all("Pumping simulation charts: Not provided." not in p.text for p in doc.paragraphs),
            "pumping_png_sha256": png}


original_run = AppTest._run


@wraps(original_run)
def app_run(self, widget_state=None, timeout=None):
    ids = {b.proto.id for b in self.button if b.label == "Build Word Document"}
    build = widget_state is not None and any(w.id in ids and w.trigger_value for w in widget_state.widgets)
    if not build:
        return original_run(self, widget_state, timeout)
    setup_start = time.perf_counter()
    state = deepcopy(self.session_state.to_dict())
    callers = []
    frame = inspect.currentframe().f_back
    while frame:
        if Path(frame.f_code.co_filename).name in ("test_audit_regressions.py", "test_uat_round3_fluids.py", "test_uat_round6_scavenger_bhct.py"):
            callers.append({"file": Path(frame.f_code.co_filename).name, "line": frame.f_lineno,
                            "function": frame.f_code.co_name, "values": {k: v for k, v in frame.f_locals.items()
                            if k in ("dosage", "job", "name") and isinstance(v, (str, float, int, type(None)))}})
        frame = frame.f_back
    override = os.environ.get("DIAG_BUILD_TIMEOUT")
    run_timeout = float(override) if override is not None else timeout
    entry = {"id": len(RECORDS) + 1, "test": NODE, "job": state.get("job_type"), "callers": callers,
             "source_signature": pumping.source_signature(state), "requested_timeout": timeout,
             "effective_timeout": self.default_timeout if run_timeout is None else run_timeout,
             "stages": [], "stage_calls": {}, "figures_before": pumping.fcm.plt.get_fignums(),
             "resource_before": snapshot(), "samples": []}
    RECORDS.append(entry)
    BY_STATE[id(self._session_state._state)] = entry
    stop = threading.Event()
    def sample():
        while not stop.wait(1):
            start = time.perf_counter()
            entry["samples"].append({"elapsed": start - entry["_start"],
                                     "active_stages": list(entry.get("_active", [])), "resource": snapshot()})
            entry["sampling_wall_seconds"] = entry.get("sampling_wall_seconds", 0) + time.perf_counter() - start
    entry["instrumentation_setup_seconds"] = time.perf_counter() - setup_start
    entry["_start"] = time.perf_counter()
    sampler = threading.Thread(target=sample, name="diagnostic-resource-sampler", daemon=True)
    sampler.start()
    try:
        return original_run(self, widget_state, run_timeout)
    except BaseException as exc:
        entry["exception"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        entry["app_build_seconds"] = time.perf_counter() - entry["_start"]
        stop.set()
        sampler.join()
        end_start = time.perf_counter()
        BY_STATE.pop(id(self._session_state._state), None)
        entry["resource_after"] = snapshot()
        entry["figures_after"] = pumping.fcm.plt.get_fignums()
        after = self.session_state.to_dict()
        entry["compiled"] = bool(after.get("_compiled_doc_bytes"))
        entry["errors"] = [e.value for e in self.error]
        entry["app_exceptions"] = [e.message for e in self.exception]
        figure, result = entry.pop("_figure", None), entry.pop("_result", None)
        if figure is not None:
            entry["owned_closed_after_run"] = not owned_open(figure)
        if result is not None:
            entry["array_signature"] = project_state.fingerprint({k: v for k, v in vars(result).items() if hasattr(v, "shape")})
            entry["result_points"] = len(result.t)
        if entry["compiled"]:
            data = after["_compiled_doc_bytes"]
            (OUT / f"build-{entry['id']:02d}.docx").write_bytes(data)
            entry["document"] = inspect_doc(data)
        entry.pop("_active", None)
        entry.pop("_start")
        entry["instrumentation_finalization_seconds"] = time.perf_counter() - end_start
        (OUT / "records.json").write_text(json.dumps(RECORDS, indent=2))
        (OUT / "solver-calls.json").write_text(json.dumps(SOLVERS, indent=2))
        print("BUILD_FINISHED", entry["id"], entry["job"], round(entry["app_build_seconds"], 3),
              entry.get("exception", "completed"), flush=True)


AppTest._run = app_run


def pytest_runtest_setup(item):
    global NODE
    NODE = item.nodeid


def pytest_runtest_logreport(report):
    if report.when == "call":
        with (OUT / "test-results.jsonl").open("a") as stream:
            stream.write(json.dumps({"node": report.nodeid, "outcome": report.outcome,
                                     "seconds": report.duration, "detail": str(report.longrepr) if report.failed else None}) + "\n")


def pytest_sessionfinish(session, exitstatus):
    (OUT / "records.json").write_text(json.dumps(RECORDS, indent=2))
    (OUT / "solver-calls.json").write_text(json.dumps(SOLVERS, indent=2))
