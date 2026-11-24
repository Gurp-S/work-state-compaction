"""SWE-CI memory probe: ingest repository history, then measure precedent retrieval.

Official SWE-CI tasks are `code.zip` + image tarballs whose `.git` history runs from the
base commit to the reference commit. This probe ingests git events up to a cutoff and asks,
at that cutoff, whether a natural-language goal retrieves commits that touched the files the
goal ends up changing. It measures the memory layer only; SWE-CI's own solve metric needs the
Linux/Docker agent stack.

    python benchmarks/swe_ci/probe.py --repo path/to/repo --holdout 20
    python benchmarks/swe_ci/probe.py --metadata metadata/default.csv \\
        --data-root data --task <task_id> --workdir .tmpfloor/swe-ci
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, repo_scope  # noqa: E402
from wsc.csm.contracts import parse_instant  # noqa: E402

SEP = "\x1e"
FIELD = "\x1f"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                          encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE).stdout


def commits(repo: Path, limit: str = "HEAD") -> list[dict]:
    """Oldest first, merges skipped; each record carries its changed paths."""
    output = git(repo, "log", "--reverse", "--no-merges", f"--format={SEP}%H{FIELD}%cI{FIELD}%s",
                 "--name-status", limit)
    out = []
    for record in output.split(SEP):
        record = record.strip("\n")
        if not record:
            continue
        lines = record.splitlines()
        sha, when, subject = lines[0].split(FIELD)
        changes = []
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0][:1] in "AMDRCTU":
                changes.append((parts[0][:1], parts[-1]))
        out.append({"sha": sha, "time": when, "subject": subject, "changes": changes})
    return out


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return ("test" in path.lower().split("/") or name.startswith("test_")
            or name.endswith("_test.py") or "/tests/" in path)


def source_files(record: dict) -> list[str]:
    return [path for status, path in record["changes"]
            if status != "D" and not is_test(path)]


def ingest(service: CSM, entity: str, records: list[dict], scope: str) -> int:
    written = 0
    for record in records:
        event_id = f"git:{record['sha']}"
        paths = [path for _, path in record["changes"]]
        payload = {"text": record["subject"], "files": paths}
        service.ingest([Event(id=event_id, source_type="git", payload=payload,
                              source_ref=record["sha"], observed_at=record["time"],
                              metadata={"commit": record["sha"], "kind": "commit"})])
        value = record["subject"] + (" | " + ", ".join(paths[:40]) if paths else "")
        service.remember([MemoryCandidate(
            entity=entity, slot="commit", value=value, property_kind="event",
            scope=scope, topics=tuple(paths[:8]) + ("commit",), source_ids=(event_id,))],
            producer="swe-ci-probe")
        written += 1
    return written


def measure(service: CSM, entity: str, scope: str, holdout: dict, top_k: int) -> dict:
    before = holdout["time"]
    packet = service.search(holdout["subject"], limit=top_k, window=(None, before),
                            scope=scope, scope_chain=True)
    rows = packet["results"]
    targets = source_files(holdout)
    text = "\n".join(str(row.get("value") or "") for row in rows)
    hit_files = [path for path in targets if path in text]
    leaked = [row for row in rows if row.get("valid_from")
              and parse_instant(row["valid_from"]) > parse_instant(before)]
    return {"sha": holdout["sha"], "subject": holdout["subject"],
            "target_files": len(targets), "files_hit": len(hit_files),
            "file_recall": round(len(hit_files) / len(targets), 4) if targets else None,
            "retrieved": len(rows), "leaked": len(leaked)}


def run_repo(repo: Path, holdout_count: int, top_k: int, db: Path) -> dict:
    history = commits(repo)
    usable = [record for record in history if source_files(record)]
    holdouts = usable[-holdout_count:]
    cutoff = history.index(holdouts[0]) if holdouts else len(history)
    train = history[:cutoff]
    entity = repo.name
    scope = repo_scope(entity)
    with tempfile.TemporaryDirectory() as directory:
        service = CSM(CsmStore(Path(directory) / "probe.db", namespace="swe-ci:probe"))
        written = ingest(service, entity, train, scope)
        results = [measure(service, entity, scope, record, top_k) for record in holdouts]
        status = service.status()
        db_size = (Path(directory) / "probe.db").stat().st_size
    return {"mode": "repo", "repo": str(repo), "commits_total": len(history),
            "ingested": written, "holdouts": len(results), "top_k": top_k,
            "file_recall_mean": round(sum(item["file_recall"] or 0 for item in results)
                                      / max(1, len(results)), 4),
            "leaked": sum(item["leaked"] for item in results),
            "status": status, "db_bytes": db_size, "results": results}


def run_task(metadata: Path, data_root: Path, task_id: str, workdir: Path,
             top_k: int) -> dict:
    rows = list(csv.DictReader(metadata.read_text(encoding="utf-8-sig").splitlines()))
    task = next((row for row in rows if row.get("task_id") == task_id), None)
    if task is None:
        raise SystemExit(f"task_missing: {task_id}")
    archive = data_root / task_id / "code.zip"
    if not archive.exists():
        raise SystemExit(f"code_archive_missing: {archive}")
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "code"
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(archive) as package:
        package.extractall(target)
    try:
        repo = next(path for path in [target, *target.iterdir()] if (path / ".git").exists())
    except StopIteration:
        raise SystemExit(f"git_repo_missing: {archive}")
    current = task.get("current_sha") or ""
    history = commits(repo)
    base_index = next((index for index, record in enumerate(history)
                       if record["sha"] == current), len(history))
    train = history[:base_index]
    entity = repo.name
    scope = repo_scope(entity)
    db_path = workdir / f"{task_id}.db"
    if db_path.exists():
        db_path.unlink()
    service = CSM(CsmStore(db_path, namespace=f"swe-ci:{task_id}"))
    written = ingest(service, entity, train, scope)
    goal = (task.get("task_id") or "").replace("_", " ")
    if current:
        try:
            subject = git(repo, "log", "-1", "--format=%s",
                          task.get("target_sha") or current).strip()
        except subprocess.CalledProcessError:
            subject = ""
        goal = f"{goal} {subject}".strip()
    packet = service.search(goal, limit=top_k, at_commit=current,
                            scope=scope, scope_chain=True) if current else \
        service.search(goal, limit=top_k, scope=scope, scope_chain=True)
    return {"mode": "task", "task": task, "ingested": written, "goal": goal,
            "status": service.status(), "retrieved": packet["results"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--workdir", type=Path, default=ROOT / ".tmpfloor" / "swe-ci")
    parser.add_argument("--holdout", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.repo:
        summary = run_repo(args.repo.resolve(), args.holdout, args.top_k,
                           args.workdir / "probe.db")
    elif args.metadata and args.data_root and args.task:
        summary = run_task(args.metadata, args.data_root, args.task, args.workdir, args.top_k)
    else:
        raise SystemExit("need --repo or --metadata/--data-root/--task")
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
