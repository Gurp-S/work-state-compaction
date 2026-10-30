"""Counterexample to implementation-specific staging rejection, not a rescore."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.acceptors import load_candidate,database


def main():
    out=Path('D:/wsc-public-workspaces/wsc-t3-runtime-admission-20261029-v7')
    candidate=out/'A/migrate.py'
    before=sha256(candidate.read_bytes()).hexdigest()
    module=load_candidate(candidate)
    db=database();created=[];dropped=[]
    try:
        db.execute('CREATE TABLE projects_migrating(sentinel TEXT)')
        db.execute("INSERT INTO projects_migrating VALUES ('keep')")
        def observe(action,first,second,schema,trigger):
            if action==sqlite3.SQLITE_CREATE_TABLE:created.append(first)
            if action==sqlite3.SQLITE_DROP_TABLE:dropped.append(first)
            return sqlite3.SQLITE_OK
        db.set_authorizer(observe)
        module.migrate(db)
        sentinel=db.execute('SELECT * FROM projects_migrating').fetchall()
        version=db.execute('SELECT version FROM schema_version').fetchall()
        assert sentinel==[('keep',)]
        assert version==[(3,)]
        assert 'projects_new' in created and 'projects_migrating' not in created
        assert 'projects_migrating' not in dropped
        assert db.in_transaction
        assert sha256(candidate.read_bytes()).hexdigest()==before
        result=dict(scope='Deterministic counterexample only; original preregistered result remains 9/10',
            candidate=str(candidate),candidate_sha256=before,created_tables=created,dropped_tables=dropped,
            preexisting_table='projects_migrating',preexisting_rows_preserved=sentinel,
            schema_version_after=3,caller_transaction_retained=True,
            collision_with_actual_created_stage=False,model_calls=0,
            original_result_changed=False,full_task_qualification=False)
    finally:db.close()
    path=out/'staging-check-counterexample.json'
    with path.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result))


if __name__=='__main__':main()
