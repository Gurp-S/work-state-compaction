"""Zero-token recall report: does repository history answer a later change goal?

For each repository, hold out the last N commits that change source files, ingest everything
before them, and query with the held-out commit subject as of its own time. A file that never
appeared in earlier history is excluded from the denominator, because no memory can retrieve
what was never written.

    python benchmarks/csm_recall.py [--holdout 20] [--top-k 10] [--repos click,httpx]

Baselines are free too: the last ten commits, and a plain subject-word scan over all prior
commit messages.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, repo_scope  # noqa: E402
from wsc.csm import index as csm_index  # noqa: E402
from wsc.csm import retrieval as csm_retrieval  # noqa: E402
from wsc.csm import symbols  # noqa: E402
from wsc.csm.contracts import parse_instant  # noqa: E402

REPOS = [
    ("pluggy", "https://github.com/pytest-dev/pluggy"),
    ("click", "https://github.com/pallets/click"),
    ("httpx", "https://github.com/encode/httpx"),
    ("starlette", "https://github.com/encode/starlette"),
    ("typer", "https://github.com/tiangolo/typer"),
]
SEP, FIELD = "\x1e", "\x1f"
WORDS = re.compile(r"[a-z0-9_]{3,}")
STOP = {"the", "and", "for", "with", "from", "into", "that", "this", "add", "fix",
        "update", "remove", "use", "using", "make", "more", "not", "are", "was", "has"}
_CLONE_LOCK = threading.Lock()
GENERIC_PATH = {"src", "lib", "py", "test", "tests", "init", "main", "utils", "core",
                "commit", "docs", "doc", "setup", "cfg", "toml"}


def path_topics(row: dict) -> list[str]:
    """Topics are the caller's path anchors; "commit" is a uniform tag, not a path."""
    return [topic for topic in (row.get("topics") or []) if topic != "commit"]


def path_expansion(results: list[dict], query: str) -> list[str]:
    """Tokens that recur in the paths of the first-pass candidates, not already in the query."""
    already = set(csm_index.terms(query))
    counts = Counter()
    for row in results[:10]:
        for topic in path_topics(row):
            for token in set(csm_index.terms(topic)):
                if token not in already and token not in GENERIC_PATH and len(token) >= 4:
                    counts[token] += 1
    return [token for token, count in counts.most_common(20) if count >= 2][:3]


def file_overlap(row: dict, seed: set[str]) -> float:
    files = set(path_topics(row))
    return len(files & seed) / max(1, len(seed))


def retrieve(core: CSM, query: str, top_k: int, window, scope: str, mode: str,
             anchor: str = "", anchor_terms: int = 8) -> list[dict]:
    def search(text: str, limit: int) -> list[dict]:
        return core.search(text, limit=limit, window=window, scope=scope,
                           scope_chain=True)["results"]

    if mode == "baseline":
        return search(query, top_k)
    if mode == "anchor-snippet":
        # The caller is editing this code: its identifiers join the query, the file path
        # does not, so the target file is not handed to retrieval.
        return core.search(query, limit=top_k, window=window, scope=scope,
                           scope_chain=True, anchor=anchor,
                           anchor_terms=anchor_terms)["results"]
    if mode == "path-expand":
        first = search(query, 30)
        tokens = path_expansion(first, query)
        return search(f"{query} {' '.join(tokens)}".strip(), top_k) if tokens \
            else first[:top_k]
    first = search(query, 200)
    seed = {topic for row in first[:5] for topic in path_topics(row)}
    if not seed:
        return first[:top_k]
    ranked = sorted(enumerate(first),
                     key=lambda pair: (-(1.0 / (60 + pair[0]) + 0.5 * file_overlap(pair[1], seed)),
                                       pair[0]))
    return [row for _, row in ranked[:top_k]]


def clone(url: str, target: Path) -> None:
    """Serialized with retries: parallel clones against GitHub get reset on this network."""
    with _CLONE_LOCK:
        if (target / ".git").exists():
            return
        error = None
        for _ in range(3):
            try:
                subprocess.run(["git", "clone", "--quiet", url, str(target)], check=True)
                return
            except subprocess.CalledProcessError as failure:
                error = failure
                time.sleep(2)
        raise error


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                          encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE).stdout


def parse_commits(repo: Path) -> list[dict]:
    output = git(repo, "log", "--reverse", "--no-merges",
                 f"--format={SEP}%H{FIELD}%cI{FIELD}%s", "--name-status", "HEAD")
    commits = []
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
        commits.append({"sha": sha, "time": when, "subject": subject, "changes": changes})
    return commits


CODE_EXTENSIONS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".rb", ".php", ".cs", ".swift", ".scala",
    ".sh", ".sql", ".css", ".html", ".vue",
})


def numstat(repo: Path, sha: str) -> dict[str, int]:
    try:
        output = git(repo, "show", "--numstat", "--format=", sha)
    except subprocess.CalledProcessError:
        return {}
    counts = {}
    for line in output.splitlines():
        parts = line.split("	")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        try:
            counts[path] = int(added) + int(removed)
        except ValueError:
            continue
    return counts


def code_anchor_file(repo: Path, commit: dict) -> str:
    """The code file with the most changed lines: the primary edit of the commit."""
    files = [path for path in source_files(commit)
             if Path(path).suffix.lower() in CODE_EXTENSIONS]
    if not files:
        return ""
    changed = numstat(repo, commit["sha"])
    return max(files, key=lambda path: (changed.get(path, 0), path))


def parent_text(repo: Path, commit: dict, path: str | None = None) -> str:
    """One changed file as it looked before the commit: what an editor shows the agent."""
    for candidate in ([path] if path else source_files(commit)):
        try:
            return git(repo, "show", f"{commit['sha']}^:{candidate}")[:20000]
        except subprocess.CalledProcessError:
            continue
    return ""


def window_text(repo: Path, commit: dict) -> str:
    """Before-view of the chosen code file: three context lines around every hunk."""
    path = code_anchor_file(repo, commit)
    if not path:
        return ""
    try:
        diff = git(repo, "diff", "--unified=3", f"{commit['sha']}^", commit["sha"],
                   "--", path)
    except subprocess.CalledProcessError:
        return parent_text(repo, commit, path)
    before = [line[1:] for line in diff.splitlines()
              if line[:1] in (" ", "-") and not line.startswith(("---", "+++"))]
    return "\n".join(before)[:20000]


def attach_symbols(repo: Path, commits: list[dict]) -> None:
    """One pass over ``git log -p``: sub-tokens of identifiers on changed lines only."""
    output = git(repo, "log", "--reverse", "--no-merges", "--format=" + SEP + "%H",
                 "--unified=0", "-p", "HEAD")
    by_sha = {commit["sha"]: commit for commit in commits}
    for record in output.split(SEP):
        if not record.strip():
            continue
        sha, _, patch = record.partition("\n")
        commit = by_sha.get(sha.strip())
        if commit is not None:
            commit["symbols"] = symbols.token_counts(patch)
            commit["removed_text"] = "\n".join(
                line[1:] for line in patch.splitlines()
                if line and not line.startswith(symbols.SKIP_PREFIX) and line[0] == "-")
    for commit in commits:
        commit.setdefault("symbols", Counter())
        commit.setdefault("removed_text", "")


def is_test(path: str) -> bool:
    parts = path.lower().split("/")
    name = parts[-1]
    return "test" in parts or name.startswith("test_") or name.endswith("_test.py")


def source_files(commit: dict) -> list[str]:
    return [path for status, path in commit["changes"]
            if status != "D" and not is_test(path)]


def remember_all(core: CSM, items: list[MemoryCandidate], chunk: int = 200) -> int:
    written = 0
    for start in range(0, len(items), chunk):
        batch = items[start:start + chunk]
        try:
            written += len(core.remember(batch, producer="recall"))
        except Exception:
            for item in batch:
                written += len(core.remember([item], producer="recall"))
    return written


def metric(core: CSM, scope: str, entity: str, holdout: dict, top_k: int,
           files_by_event: dict[str, set[str]], prior_files: set[str],
           mode: str = "baseline", anchor: str = "", anchor_terms: int = 8) -> dict:
    began = time.perf_counter()
    rows = retrieve(core, holdout["subject"], top_k, (None, holdout["time"]), scope, mode,
                    anchor, anchor_terms)
    latency = time.perf_counter() - began
    retrieved = [files_by_event.get((row.get("source_refs") or [None])[0], set())
                 for row in rows]
    targets = source_files(holdout)
    precedent = [path for path in targets if path in prior_files]
    found = {path for paths in retrieved for path in paths}
    found5 = {path for paths in retrieved[:5] for path in paths}
    targets_set = set(targets)
    mrr = 0.0
    for rank, paths in enumerate(retrieved):
        if paths & targets_set:
            mrr = 1.0 / (rank + 1)
            break
    leaked = sum(1 for row in rows if row.get("valid_from")
                 and parse_instant(row["valid_from"]) > parse_instant(holdout["time"]))
    return {"sha": holdout["sha"], "subject": holdout["subject"],
            "target_files": len(targets), "precedent_files": len(precedent),
            "recall": round(len(set(precedent) & found) / len(precedent), 4)
            if precedent else None,
            "recall_at_5": round(len(set(precedent) & found5) / len(precedent), 4)
            if precedent else None,
            "commit_hit": bool(found & targets_set),
            "mrr": round(mrr, 4), "latency_s": round(latency, 4), "leaked": leaked}


def baseline(holdout: dict, prior: list[dict], precedent: list[str], top_k: int,
             mode: str) -> float | None:
    if not precedent:
        return None
    if mode == "recent":
        chosen = prior[-top_k:]
    else:
        words = set(WORDS.findall(holdout["subject"].lower())) - STOP
        scored = []
        for index, commit in enumerate(prior):
            overlap = len(words & set(WORDS.findall(commit["subject"].lower())))
            if overlap:
                scored.append((-overlap, index, commit))
        chosen = [item[2] for item in sorted(scored)[:top_k]]
    found = {path for commit in chosen for path in source_files(commit)}
    return round(len(set(precedent) & found) / len(precedent), 4)


def analyse(name: str, url: str, holdout_count: int, top_k: int,
            clones: Path, holdout_shas: list[str] | None = None,
            mode: str = "baseline", symbols_mode: str = "off",
            anchor_source: str = "removed", anchor_terms: int = 8) -> dict:
    repo = clones / name
    clone(url, repo)
    history = parse_commits(repo)
    if holdout_shas:
        by_sha = {commit["sha"]: commit for commit in history}
        holdouts = [by_sha[sha] for sha in holdout_shas if sha in by_sha]
    else:
        usable = [commit for commit in history
                  if source_files(commit) and commit["subject"]]
        holdouts = usable[-holdout_count:]
    train = history[:history.index(holdouts[0])] if holdouts else []
    if symbols_mode != "off" or mode == "anchor-snippet":
        attach_symbols(repo, history)
    else:
        for commit in history:
            commit["symbols"] = Counter()
            commit["removed"] = Counter()
    if mode == "anchor-snippet":
        anchors = []
        for commit in holdouts:
            if anchor_source == "window":
                anchors.append(window_text(repo, commit))
            elif anchor_source == "code":
                anchors.append(parent_text(repo, commit, code_anchor_file(repo, commit)))
            elif anchor_source == "file":
                anchors.append(parent_text(repo, commit))
            else:
                anchors.append(commit.get("removed_text", ""))
    else:
        anchors = [""] * len(holdouts)
    keep = None
    if symbols_mode == "df" and train:
        frequency = symbols.document_frequency(
            [set(commit["symbols"]) for commit in train])
        cutoff = max(3, int(0.05 * len(train)))
        keep = {token for token, count in frequency.items() if count <= cutoff}
    entity = name
    scope = repo_scope(entity)
    started = time.time()
    with tempfile.TemporaryDirectory() as directory:
        db = Path(directory) / "recall.db"
        core = CSM(CsmStore(db, namespace=f"recall:{name}"))
        events, candidates, symbol_lists = [], [], []
        for commit in train:
            event_id = f"git:{commit['sha']}"
            paths = [path for _, path in commit["changes"]]
            events.append(Event(id=event_id, source_type="git",
                                payload={"text": commit["subject"], "files": paths},
                                source_ref=commit["sha"], observed_at=commit["time"],
                                metadata={"commit": commit["sha"], "kind": "commit"}))
            value = commit["subject"] + (" | " + ", ".join(paths[:40]) if paths else "")
            selected = tuple(symbols.select(commit["symbols"], keep))
            symbol_lists.append(selected)
            candidates.append(MemoryCandidate(
                entity=entity, slot="commit", value=value, property_kind="event",
                scope=scope, topics=tuple(paths[:8]) + ("commit",), symbols=selected,
                source_ids=(event_id,)))
        core.ingest(events)
        written = remember_all(core, candidates)
        files_by_event = {f"git:{commit['sha']}": set(source_files(commit)) for commit in train}
        prior_files = {path for commit in train for path in source_files(commit)}
        results = [metric(core, scope, entity, holdout, top_k, files_by_event, prior_files,
                          mode, anchor, anchor_terms)
                   for holdout, anchor in zip(holdouts, anchors)]
        status = core.status()
        size = db.stat().st_size
    for row, holdout in zip(results, holdouts):
        targets = source_files(holdout)
        precedent = [path for path in targets if path in prior_files]
        row["recent_baseline"] = baseline(holdout, train, precedent, top_k, "recent")
        row["message_baseline"] = baseline(holdout, train, precedent, top_k, "message")
    scored = [row for row in results if row["recall"] is not None]
    latencies = sorted(row["latency_s"] for row in results)
    return {"repo": name, "commits": len(history), "ingested": written,
            "retrieval": mode, "symbols": symbols_mode,
            "anchor_source": anchor_source, "anchor_terms": anchor_terms,
            "symbols_per_commit": round(statistics.mean(len(item) for item in symbol_lists), 2)
            if symbol_lists else 0,
            "holdouts": len(results), "scored_holdouts": len(scored),
            "recall": round(statistics.mean(row["recall"] for row in scored), 4)
            if scored else None,
            "recall_at_5": round(statistics.mean(
                row["recall_at_5"] for row in scored), 4) if scored else None,
            "commit_hit_rate": round(sum(row["commit_hit"] for row in scored)
                                     / len(scored), 4) if scored else None,
            "mrr": round(statistics.mean(row["mrr"] for row in scored), 4)
            if scored else None,
            "recent_baseline": round(statistics.mean(
                row["recent_baseline"] for row in scored), 4) if scored else None,
            "message_baseline": round(statistics.mean(
                row["message_baseline"] for row in scored), 4) if scored else None,
            "leaked": sum(row["leaked"] for row in results),
            "latency_p50_s": round(statistics.median(latencies), 4),
            "latency_p95_s": round(latencies[min(len(latencies) - 1,
                                                 int(len(latencies) * 0.95))], 4),
            "db_mb": round(size / (1024 * 1024), 2), "status": status,
            "seconds": round(time.time() - started, 1), "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--clones", type=Path, default=ROOT / ".tmpfloor" / "recall-repos")
    parser.add_argument("--clean-clones", action="store_true",
                        help="delete the clone cache after the run (A/B reuses it otherwise)")
    parser.add_argument("--clone-base", default="",
                        help="optional proxy prefix, e.g. https://ghproxy.net/")
    parser.add_argument("--term-variant", choices=("both", "refs", "template", "off"),
                        default="both",
                        help="A/B switch for issue-reference and template normalization")
    parser.add_argument("--template-words",
                        help="comma separated override for the template stoplist")
    parser.add_argument("--retrieval", choices=("baseline", "path-expand", "same-file",
                                                "anchor-snippet"),
                        default="baseline",
                        help="query-side A/B: baseline, path expansion, same-file rerank, "
                             "or the editing code snippet as an anchor")
    parser.add_argument("--symbols", choices=("off", "shape", "df"), default="shape",
                        help="second index from diff identifiers; df adds a train-corpus gate")
    parser.add_argument("--symbol-weight", type=float, default=1.0,
                        help="symbol score multiplier; ignored when --symbols off")
    parser.add_argument("--symbol-cap", type=float, default=0.0,
                        help="ceiling on one revision's symbol score before weighting")
    parser.add_argument("--symbol-gate-k", type=int, default=0,
                        help="consult symbols only when lexical candidates are fewer than k")
    parser.add_argument("--symbol-gate-score", type=float, default=0.0,
                        help="consult symbols only when the top lexical score is below this")
    parser.add_argument("--anchor-source", choices=("removed", "file", "code", "window"), default="removed",
                        help="anchor text: removed lines, first file, chosen code file, or its diff window")
    parser.add_argument("--anchor-terms", type=int, default=8,
                        help="identifier keys taken from the anchor text")
    parser.add_argument("--repos", default="",
                        help="comma separated names; default all five")
    parser.add_argument("--holdouts-from", type=Path,
                        help="reuse the holdout SHAs recorded in an earlier run JSON")
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results" /
                        f"csm-recall-5repo-{time.strftime('%Y%m%d')}.json")
    args = parser.parse_args()
    args.clones.mkdir(parents=True, exist_ok=True)
    if args.term_variant in ("off", "template"):
        csm_index._REF = re.compile(r"(?!)")
    if args.term_variant in ("off", "refs"):
        csm_index._TEMPLATE = frozenset()
    if args.template_words:
        csm_index._TEMPLATE = frozenset(
            word.strip().lower() for word in args.template_words.split(",") if word.strip())
    csm_retrieval.SYMBOL_WEIGHT = 0.0 if args.symbols == "off" else args.symbol_weight
    csm_retrieval.SYMBOL_CAP = 0.0 if args.symbols == "off" else args.symbol_cap
    csm_retrieval.SYMBOL_GATE_K = 0 if args.symbols == "off" else args.symbol_gate_k
    csm_retrieval.SYMBOL_GATE_SCORE = (0.0 if args.symbols == "off"
                                       else args.symbol_gate_score)
    selected = {item.strip() for item in args.repos.split(",") if item.strip()}
    repos = [(name, (args.clone_base + url) if args.clone_base else url)
             for name, url in REPOS if not selected or name in selected]
    fixed: dict[str, list[str]] = {}
    if args.holdouts_from:
        previous = json.loads(args.holdouts_from.read_text(encoding="utf-8"))
        fixed = {report["repo"]: [row["sha"] for row in report.get("results") or []]
                 for report in previous.get("reports") or [] if report.get("results")}
    reports = []
    with ThreadPoolExecutor(max_workers=len(repos)) as pool:
        futures = {pool.submit(analyse, name, url, args.holdout, args.top_k, args.clones,
                               fixed.get(name), args.retrieval, args.symbols,
                               args.anchor_source, args.anchor_terms): name
                   for name, url in repos}
        for future in futures:
            name = futures[future]
            try:
                reports.append(future.result())
                print(f"done {name}", flush=True)
            except Exception as error:
                print(f"failed {name}: {type(error).__name__}: {error}", flush=True)
                reports.append({"repo": name, "error": f"{type(error).__name__}: {error}"})
    scored = [report for report in reports
              if report.get("recall") is not None]
    summary = {"repos": len(reports), "scored_repos": len(scored), "holdout": args.holdout,
               "top_k": args.top_k, "term_variant": args.term_variant,
               "retrieval": args.retrieval, "symbols": args.symbols,
               "symbol_weight": 0.0 if args.symbols == "off" else args.symbol_weight,
               "symbol_cap": 0.0 if args.symbols == "off" else args.symbol_cap,
               "symbol_gate_k": 0 if args.symbols == "off" else args.symbol_gate_k,
               "symbol_gate_score": 0.0 if args.symbols == "off" else args.symbol_gate_score,
               "anchor_source": args.anchor_source, "anchor_terms": args.anchor_terms,
               "recall": round(statistics.mean(report["recall"] for report in scored), 4)
               if scored else None,
               "recall_at_5": round(statistics.mean(report["recall_at_5"]
                                                    for report in scored), 4)
               if scored else None,
               "recent_baseline": round(statistics.mean(
                   report["recent_baseline"] for report in scored), 4) if scored else None,
               "message_baseline": round(statistics.mean(
                   report["message_baseline"] for report in scored), 4) if scored else None,
               "commit_hit_rate": round(statistics.mean(
                   report["commit_hit_rate"] for report in scored), 4) if scored else None,
               "mrr": round(statistics.mean(report["mrr"] for report in scored), 4)
               if scored else None,
               "leaked": sum(report.get("leaked") or 0 for report in reports),
               "latency_p95_s": round(max(
                   (report.get("latency_p95_s") or 0) for report in reports), 4),
               "reports": reports}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in
                      ("repos", "scored_repos", "recall", "recent_baseline",
                       "message_baseline", "commit_hit_rate", "mrr", "leaked",
                       "latency_p95_s")}, ensure_ascii=False))
    if args.clean_clones:
        shutil.rmtree(args.clones, ignore_errors=True)


if __name__ == "__main__":
    main()
