"""Run only the owner-approved methods; never change tracked tests or inputs."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

RC = "ee89898ddfd9b4308a0dee6f09cf4e67834b7ba9"
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["RUNNER_TEMP"]) / "round10-hosted-timeout"
NODES = [
    "tests/test_audit_regressions.py::AuditRegressions::test_batch1_calculation_errors_block_export",
    "tests/test_audit_regressions.py::AuditRegressions::test_batch4_spacer_zero_positive_and_missing_dosage",
    "tests/test_uat_round3_fluids.py::Round3FluidsUAT::test_actual_word_name_and_detailed_rows_independent_for_five_jobs",
    "tests/test_uat_round6_scavenger_bhct.py::test_all_five_normal_lab_sections_share_well_conditions_and_exclude_scavenger",
]
PROTECTED = {
    "fluids_charts_module_v1_4_2.py": "ceaaff1311b241c8793fc65b0004a8ca28bef463d93db0957d9b650522bdc5ea",
    "master_template.docx": "0c3d911e471aae22c0b18fecc53ed99caa7e7479d94b22640bc19439da92e331",
    "centralizer_optimizer_engine.py": "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9",
    "cement_charts_engine.py": "68b275c0c3fd0e804a926d39e1123b451f7e22b2c5aad31f6d0ab3e8236709d4",
    "ds_cent_products.json": "837010c1a67a7a9252317f4b2e9b8f08b29f39f431cc8e45cfcc5eb6c94a1329",
    "requirements.txt": "e59b8b0f925d3246dad4bfa32d0669ddb96f4eaf22d124ac5aa0e9fa03805610",
    "test_regression_guardrails.py": "38c2ae0a7926d7b7a7aaa286981cb4bca6fa72d71f04efd8c8406794a5cf6231",
}


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def integrity():
    changed = command("git", "diff", "--name-only", RC, "HEAD").splitlines()
    assert changed and all(p == ".github/workflows/round10-hosted-diagnostic.yml" or
                           p.startswith(".github/diagnostics/") for p in changed), changed
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PROTECTED}
    assert hashes == PROTECTED, hashes
    assert not command("git", "status", "--porcelain=v1", "-uall")
    return {"head": command("git", "rev-parse", "HEAD"), "rc": RC,
            "changed": changed, "protected_hashes": hashes}


def read(path):
    p = Path(path)
    return p.read_text() if p.exists() else None


def run(label, timeout=None):
    destination = OUT / label
    destination.mkdir()
    env = {**os.environ, "DIAG_DIR": str(destination), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join((str(Path(__file__).parent.resolve()), str(ROOT), str(ROOT / "tests")))}
    env.pop("DIAG_BUILD_TIMEOUT", None)
    if timeout is not None:
        env["DIAG_BUILD_TIMEOUT"] = str(timeout)
    args = [sys.executable, "-B", "-m", "pytest", "-p", "round10_timing_plugin", *NODES,
            "-q", "-ra", "-p", "no:cacheprovider"]
    print("DIAGNOSTIC_COMMAND", label, json.dumps(args), "runtime_build_timeout", timeout, flush=True)
    start = time.perf_counter()
    with (destination / "pytest.log").open("w") as log:
        result = subprocess.run(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    records = json.loads((destination / "records.json").read_text())
    summary = {"label": label, "returncode": result.returncode, "seconds": time.perf_counter() - start,
               "command": args, "runtime_build_timeout": timeout,
               "builds": len(records), "timeouts": [r["id"] for r in records if
                   "AppTest script run timed out after 30(s)" in r.get("exception", "")],
               "all_solver_calls": json.loads((destination / "solver-calls.json").read_text())}
    print((destination / "pytest.log").read_text(), flush=True)
    for record in records:
        compact = {k: v for k, v in record.items() if k != "samples"}
        compact["boundary_samples"] = [s for s in record["samples"] if 29 <= s["elapsed"] <= 31.5]
        print("BUILD_EVIDENCE", label, json.dumps(compact), flush=True)
    print("PASS_EVIDENCE", json.dumps(summary), flush=True)
    return summary


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    environment = {"python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "affinity": sorted(os.sched_getaffinity(0)), "os_release": read("/etc/os-release"),
        "cpuinfo": read("/proc/cpuinfo"), "meminfo": read("/proc/meminfo"),
        "cpu_max": read("/sys/fs/cgroup/cpu.max"), "cpu_stat": read("/sys/fs/cgroup/cpu.stat"),
        "memory_max": read("/sys/fs/cgroup/memory.max"), "loadavg": read("/proc/loadavg"),
        "runner": {key: os.environ.get(key) for key in (
            "ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH", "RUNNER_NAME", "GITHUB_SHA",
            "GITHUB_REF", "GITHUB_RUN_ID", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MPLBACKEND")},
        "pip_freeze": command(sys.executable, "-m", "pip", "freeze"), "integrity_before": integrity()}
    (OUT / "environment.json").write_text(json.dumps(environment, indent=2))
    print("ENVIRONMENT_EVIDENCE", json.dumps(environment), flush=True)
    results = [run("baseline30")]
    if results[0]["timeouts"]:
        results.append(run("completion120", 120))
    else:
        print("COMPLETION_PROBE_NOT_RUN: no original 30-second Build timeout reproduced.", flush=True)
    summary = {"passes": results, "integrity_after": integrity()}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print("FINAL_EVIDENCE", json.dumps(summary), flush=True)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as report:
        report.write("Diagnostic collection completed; this is not regression certification.\n\n")
        for result in results:
            report.write(f"- {result['label']}: pytest exit {result['returncode']}, "
                         f"{result['builds']} Builds, {result['seconds']:.3f}s; "
                         f"30s timeouts: {result['timeouts']}\n")
    # Original failures are retained in logs/artifacts, never converted into test passes.
    # Only the evidence-collection job continues to the conditional completion probe.


if __name__ == "__main__":
    main()
