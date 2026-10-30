"""Reuse this Python 3.11 installation in an owned workspace; no download."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile,ZIP_DEFLATED


def manifest(runtime):
    result={}
    for path in sorted(Path(runtime).rglob('*')):
        if not path.is_file() or path.name=='runtime-manifest.json':continue
        h=sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1048576),b''):h.update(block)
        result[path.relative_to(runtime).as_posix()]=dict(sha256=h.hexdigest(),bytes=path.stat().st_size)
    return dict(version=sys.version.split()[0],files=result,bytes=sum(v['bytes'] for v in result.values()),
        scope='Existing workspace runtime assets only; native execution must be qualified separately.')


def prepare(destination):
    if sys.version_info[:2]!=(3,11):raise ValueError('python_311_required')
    source=Path(sys.executable).resolve().parent
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(sys.executable,destination/'python.exe')
    for path in source.glob('*.dll'):shutil.copyfile(path,destination/path.name)
    shutil.copytree(source/'DLLs',destination/'DLLs')
    excluded={'site-packages','__pycache__','test','idlelib','tkinter','turtledemo','ensurepip','venv'}
    with ZipFile(destination/'stdlib.zip','x',compression=ZIP_DEFLATED) as archive:
        for path in (source/'Lib').rglob('*'):
            relative=path.relative_to(source/'Lib')
            if path.is_file() and not excluded.intersection(relative.parts):archive.write(path,relative.as_posix())
    (destination/'python311._pth').write_bytes(b'stdlib.zip\nDLLs\n.\n')
    result=manifest(destination)
    (destination/'runtime-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    value=prepare(parser.parse_args().destination)
    print(json.dumps(dict(version=value['version'],bytes=value['bytes'],files=len(value['files']))))
