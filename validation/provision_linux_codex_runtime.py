"""Extract only the non-voice native runtime from an integrity-verified package."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

PREFIX = 'package/vendor/x86_64-unknown-linux-musl/'
FILES = ('bin/codex', 'bin/codex-code-mode-host', 'codex-path/rg',
         'codex-resources/bwrap', 'codex-package.json')


def main(metadata, archive, out):
    meta=json.loads(metadata.read_text(encoding='utf-8'))
    if meta.get('name')!='@openai/codex' or meta.get('version')!='0.165.0-alpha.1.2-linux-x64':
        raise ValueError('linux_runtime_package_unregistered')
    value=hashlib.sha512()
    with archive.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    if 'sha512-'+base64.b64encode(value.digest()).decode()!=meta['dist']['integrity']:
        raise ValueError('linux_runtime_package_integrity_mismatch')
    out.mkdir(parents=True,exist_ok=False)
    manifest={}
    with tarfile.open(archive,'r:gz') as package:
        names={}
        for member in package.getmembers():
            if member.name in names:raise ValueError('linux_runtime_duplicate_member')
            names[member.name]=member
        for name in FILES:
            member=names[PREFIX+name]
            relative=PurePosixPath(name)
            if not member.isfile() or member.size>335544320 or relative.is_absolute() or '..' in relative.parts:
                raise ValueError('linux_runtime_member_invalid')
            target=out/name;target.parent.mkdir(parents=True,exist_ok=True)
            source=package.extractfile(member)
            if source is None:raise ValueError('linux_runtime_member_missing')
            with source, target.open('xb') as stream:shutil.copyfileobj(source,stream,1048576)
            if target.stat().st_size!=member.size:raise ValueError('linux_runtime_member_truncated')
            target.chmod(0o755 if name!='codex-package.json' else 0o644)
            h=hashlib.sha256()
            with target.open('rb') as stream:
                for block in iter(lambda:stream.read(1048576),b''):h.update(block)
            manifest[name]=dict(bytes=member.size,sha256=h.hexdigest())
    with (out/'runtime-manifest.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(version='0.165.0-alpha.1.2',platform='linux-x64',files=manifest,
                       package_integrity=meta['dist']['integrity'],voice_runtime_included=False,
                       scope='Non-voice benchmark runtime; native binary bytes unchanged'),stream,indent=2)
    print(json.dumps(dict(files=len(manifest),bytes=sum(v['bytes'] for v in manifest.values()),out=str(out))))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--metadata',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();main(args.metadata,args.archive,args.out)
