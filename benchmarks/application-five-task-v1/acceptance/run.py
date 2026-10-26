"""Run public HTTP checks against an isolated submission, not a reference answer.

Usage: python -B -X utf8 run.py TASK ABS_WORKSPACE ABS_NEW_OUTPUT --stage 8
Exit 0 means checks completed; result.json contains quality failures. Exit 2 is
runner/infrastructure failure. Neither exit status certifies full application.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import traceback

from cases import CASES, seed_legacy
import extended_cases  # Registers additional public checks before selecting a stage.
from runtime import App, manifest, save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('task', choices=sorted(CASES))
    parser.add_argument('workspace', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--stage', type=int, choices=range(1, 9), default=8)
    args = parser.parse_args()
    assert args.workspace.is_absolute() and args.output.is_absolute(), 'absolute_paths_required'
    workspace, output = args.workspace.resolve(), args.output.resolve()
    assert workspace.is_dir() and (workspace / 'backend/server.py').is_file(), 'submission_missing'
    assert not output.is_relative_to(workspace) and not workspace.is_relative_to(output), 'output_workspace_overlap'
    output.mkdir(parents=True, exist_ok=False)
    suite = Path(__file__).resolve().parents[1]
    task_dir = suite / 'tasks' / args.task
    initial = manifest(workspace)
    registration = dict(task=args.task, stage=args.stage, workspace=str(workspace),
        source_manifest=initial, acceptance_manifest=manifest(Path(__file__).parent),
        contract_manifest={str(p.relative_to(suite)): sha256(p.read_bytes()).hexdigest()
                           for p in [suite / 'COMMON.md', task_dir / 'TASK.md', task_dir / 'task.json']},
        runtime=dict(executable=sys.executable, version=sys.version, sha256=sha256(Path(sys.executable).read_bytes()).hexdigest()),
        started_at=datetime.now(timezone.utc).isoformat(), manual_complete=False)
    save(output / 'registration.json', registration)
    results = []
    try:
        for name, stage, function in CASES[args.task]:
            if stage > args.stage:
                continue
            area = output / name
            area.mkdir()
            app = App(workspace, area)
            started = time.monotonic()
            outcome = dict(id=name, stage=stage, passed=False)
            try:
                if name == 'legacy_migration_twice':
                    seed_legacy(app)
                app.start()
                function(app)
                outcome['passed'] = True
            except Exception as error:
                outcome['failure'] = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
            finally:
                app.stop()
                outcome.update(elapsed_seconds=time.monotonic() - started, events=app.events)
                save(area / 'receipt.json', outcome)
            results.append({key: outcome[key] for key in ('id', 'stage', 'passed')})
        unchanged = manifest(workspace) == initial
        result = dict(status='completed_public_http_checks', task=args.task, stage=args.stage,
            outcomes=results, checks=len(results), passes=sum(r['passed'] for r in results),
            source_unchanged=unchanged, full_task_qualified=False, manual_review_pending=True,
            coverage='Representative public HTTP checks, not complete domain or browser coverage',
            model_calls=0)
        save(output / 'result.json', result)
        assert unchanged, 'submission_changed_during_grading'
        print(json.dumps(result, ensure_ascii=False))
    except BaseException as error:
        save(output / 'infrastructure-error.json', dict(type=type(error).__name__, message=str(error),
             traceback=traceback.format_exc(), completed=results))
        raise


if __name__ == '__main__':
    main()
