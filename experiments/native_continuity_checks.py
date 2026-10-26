"""Version-bound, private-copy acceptance for the frozen continuity task."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from native_evidence import FIELDS, digest, file_hash, manifest, read, save


def require(value, reason):
    if not value:
        raise ValueError(reason)


def archive_workspace(workspace, destination):
    before = manifest(workspace)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in before:
            archive.write(Path(workspace) / name, name)
    with zipfile.ZipFile(destination) as archive:
        from hashlib import sha256
        require({name: sha256(archive.read(name)).hexdigest() for name in archive.namelist()} == before,
                "continuity_archive_source_changed")
    require(manifest(workspace) == before, "continuity_workspace_changed_during_archive")
    return {"manifest": before, "manifest_sha256": digest(before), "path": str(destination),
            "sha256": file_hash(destination)}


def grade(workspace, grader, scope, destination):
    require(scope in {"RevisionContractTests", "all"}, "continuity_check_scope_unknown")
    workspace, destination = Path(workspace), Path(destination)
    before = manifest(workspace)
    destination.mkdir()
    fixture = destination / "fixture"
    fixture.mkdir()
    shutil.copytree(workspace / "src", fixture / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    require(manifest(fixture / "src") == manifest(workspace / "src"), "continuity_check_copy_changed")
    (fixture / "tests").mkdir()
    shutil.copy2(grader, fixture / "tests" / "_continuity_grader.py")
    probe = '''import io, json, pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path('tests').resolve()))
import _continuity_grader as module
import wsc
loader=unittest.defaultTestLoader
suite=loader.loadTestsFromModule(module) if sys.argv[1]=='all' else loader.loadTestsFromTestCase(getattr(module, sys.argv[1]))
stream=io.StringIO()
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
print(json.dumps(dict(tests=result.testsRun, failures=[dict(test=t.id(),trace=s) for t,s in result.failures], errors=[dict(test=t.id(),trace=s) for t,s in result.errors], skipped=len(result.skipped), imported_from=wsc.__file__, log=stream.getvalue())))
'''
    process = subprocess.run([sys.executable, "-B", "-c", probe, scope], cwd=fixture,
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
    (destination / "stdout.txt").write_text(process.stdout, encoding="utf-8")
    (destination / "stderr.txt").write_text(process.stderr, encoding="utf-8")
    require(process.returncode == 0, "continuity_grader_process_failed")
    import json
    result = json.loads(process.stdout)
    require(Path(result["imported_from"]).resolve().is_relative_to((fixture / "src").resolve()),
            "continuity_grader_import_wrong_source")
    require(manifest(workspace) == before, "continuity_check_changed_task_workspace")
    # The check runs only copied source; retain a compact source snapshot elsewhere.
    result.update(source_manifest=before, source_manifest_sha256=digest(before), scope=scope,
                  grader_sha256=file_hash(grader), cash=None,
                  passed=not (result["failures"] or result["errors"] or result["skipped"])
                         and result["tests"] == (9 if scope == "all" else 6))
    save(destination / "receipt.json", result)
    return result


def prior_check_fact(receipt, path):
    return {"receipt_path": str(path), "source_manifest_sha256": receipt["source_manifest_sha256"],
            "scope": receipt["scope"], "test_methods": receipt["tests"], "passed": receipt["passed"],
            "grader_sha256": receipt["grader_sha256"]}


def aggregate(phases):
    seen, known, complete = set(), dict.fromkeys(FIELDS, 0), True
    for outcome in phases:
        complete &= bool(outcome.get("usage_complete"))
        receipt = outcome.get("receipts")
        if receipt is None:
            complete = False
            continue
        for response in receipt["response_receipts"]:
            rid = response["response_id"]
            require(rid not in seen, "continuity_response_billed_twice")
            seen.add(rid)
            for field in FIELDS:
                known[field] += response["usage"][field]
    return {"response_count": len(seen), "response_ids": sorted(seen), "known_usage": known,
            "complete_usage": known if complete else None, "complete": bool(complete),
            "cash": None, "price_status": "unknown"}
