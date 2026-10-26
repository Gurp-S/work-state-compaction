"""Preserve trial deltas before exact S2 reuse; never copy private runtimes."""
from pathlib import Path
from hashlib import sha256
import zipfile
from native_evidence import save, file_hash
from native_application_session import NativeApplicationSession


def restore(registration, frozen, destination, *, expected_current=None):
    work, frozen, output = (Path(p).resolve() for p in (registration['workspace'], frozen, destination))
    if output.is_relative_to(work) or work.is_relative_to(output) or work.drive != output.drive:
        raise ValueError('S2_restore_archive_boundary_invalid')
    output.mkdir(parents=True, exist_ok=False)
    measured = NativeApplicationSession(registration, output/'inspection-only')
    before = measured.source_manifest()
    if expected_current is not None and before != expected_current:
        raise ValueError('S2_restore_source_changed_before_preservation')
    expected = registration['initial_manifest']
    if not all((frozen/key).is_file() and file_hash(frozen/key)==value for key,value in expected.items()):
        raise ValueError('S2_restore_baseline_changed')
    changed = [key for key in expected if key in before and before[key]!=expected[key]]
    missing = sorted(set(expected)-set(before))
    extra = sorted(set(before)-set(expected))
    save(output/'before-manifest.json',before)
    archive = output/'changed-source.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as zipped:
        for key in changed:zipped.write(work/key,key)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None and all(sha256(zipped.read(k)).hexdigest()==before[k] for k in changed)
    parents = {str(Path(key).parent).replace('\\','/') for key in expected}
    parents |= {str(p).replace('\\','/') for key in expected for p in Path(key).parents}
    roots = set()
    for key in extra:
        parts=Path(key).parts
        roots.add(next('/'.join(parts[:i]) for i in range(1,len(parts)+1) if '/'.join(parts[:i]) not in parents))
    retained=output/'retained-extra'
    retained.mkdir()
    moves=[]
    for key in sorted(roots):
        source=(work/key).resolve(); target=(retained/key).resolve()
        if (not source.is_relative_to(work) or not target.is_relative_to(retained)
                or source.lstat().st_file_attributes & 1024 or target.exists()
                or any(k==key or k.startswith(key+'/') for k in expected)):
            raise ValueError('S2_restore_move_boundary_invalid')
        moves.append(dict(relative=key,source=str(source),target=str(target)))
    save(output/'move-plan.json',moves)
    private=[work/'gui/node_modules',work/'.wsc-runtime/browsers']
    identities={str(p):p.stat().st_ino for p in private}
    for move in moves:
        target=Path(move['target']);target.parent.mkdir(parents=True,exist_ok=True)
        Path(move['source']).rename(target)
    for key in extra:
        if file_hash(retained/key)!=before[key]:raise ValueError('S2_restore_retained_extra_changed')
    for key in [*changed,*missing]:
        target=(work/key).resolve()
        if not target.is_relative_to(work):raise ValueError('S2_restore_write_boundary_invalid')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((frozen/key).read_bytes())
    if measured.source_manifest()!=expected:raise ValueError('S2_restore_exact_manifest_mismatch')
    if any(p.stat().st_ino!=identities[str(p)] for p in private):raise ValueError('S2_restore_private_runtime_changed')
    result=dict(exact_S2_restored=True,changed_files=changed,restored_missing=missing,retained_extra_count=len(extra),
        changed_archive_sha256=file_hash(archive),private_directory_identities=identities,model_calls=0)
    save(output/'result.json',result)
    return result
