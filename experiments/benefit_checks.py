"""Pinned historical business checker plus the same five artifact-owned tests.

Only stdlib-only historical evidence/checker modules are loaded. No historical
actor, provider, bootstrap or WSC engine module is imported.
"""
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from native_evidence import file_hash, python_manifest, save

ARCHIVE = Path(__file__).resolve().parents[2] / "_wsc_out/handoff-v10-20261018"
CHECKS = ARCHIVE / "wsc-fusion-v1"
TARGETS = ("python/scripts/_wsc_jsonl_source.py", "python/scripts/wsc_pairing_report.py",
           "python/tests/wsc/test_pairing_report_source_fidelity.py", "python/usage/pairing.py")
APP = Path("C:/Users/48522/AppData/Local/Programs/Python/Python311/python.exe")


def dependencies():
    return [CHECKS / name for name in ("source_fidelity_oracle.py", "usage_oracle_isolation.py",
            "registered_unittest_recording.py", "registered_artifact_receipt_view.py",
            "registered_artifact_receipt_view_v2.py")] + [ARCHIVE / "long-study-v1/business_oracle.py"]


def load(name):
    spec = importlib.util.spec_from_file_location(name, CHECKS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Checker:
    def __init__(self, protected_pairing):
        sys.path.insert(0, str(CHECKS))
        self.business = load("source_fidelity_oracle")
        self.recorded = load("registered_unittest_recording").Recorded
        self.project = load("registered_artifact_receipt_view_v2").project
        self.protected = protected_pairing

    def run(self, work, output):
        before = python_manifest(work)
        report = self.business.check(output / "business", work, interpreter=APP,
                                     protected_pairing_sha=self.protected)
        worker = """import contextlib,importlib.util,io,json,pathlib,sys,unittest
root=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(root/'python'))
spec=importlib.util.spec_from_file_location('owned_source_fidelity_tests',root/sys.argv[2])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
""" + inspect.getsource(self.recorded) + """
result=Recorded();output=io.StringIO()
with contextlib.redirect_stdout(output):unittest.defaultTestLoader.loadTestsFromModule(module).run(result)
print(json.dumps({'tests_run':result.testsRun,'cases':result.rows,'captured_stdout':output.getvalue()}))
"""
        proc = subprocess.run([str(APP), "-I", "-B", "-c", worker, str(work), TARGETS[2]],
            cwd=work / "python", env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, encoding="utf-8", timeout=40)
        save(output / "owned-process.json", {"returncode": proc.returncode,
                                             "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            raise ValueError("owned_checker_process_failed")
        owned = json.loads(proc.stdout)
        if owned["tests_run"] != 5 or len(owned["cases"]) != 5:
            raise ValueError("owned_checker_scope_changed")
        if python_manifest(work) != before:
            raise ValueError("checker_changed_source")
        cases = report["cases"] + [dict(c, name="owned_regression:" + c["name"],
                                           group="actual_owned_tests") for c in owned["cases"]]
        report = {**report, "run_id": "independent-wsc-check-" + uuid.uuid4().hex,
                  "cases": cases, "passed": sum(c["passed"] for c in cases), "total": len(cases),
                  "complete_named_suite_pass": all(c["passed"] for c in cases),
                  "groups": {"business": {"passed": report["passed"], "total": 13},
                             "owned_regression": {"passed": sum(c["passed"] for c in owned["cases"]), "total": 5}},
                  "verification": {**report["verification"], "scope":
                      "13 named source-fidelity cases and 5 existing owned unittest tests only; not full-project certification."}}
        report = self.project(report, TARGETS)
        save(output / "report.json", report)
        return report
