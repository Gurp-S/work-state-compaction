"""Pin and verify the upstream stripped musl Python runtime; no global install."""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import tarfile
import time
from urllib.request import Request, urlopen

NAME = 'cpython-3.11.18+20261026-x86_64-unknown-linux-musl-install_only_stripped.tar.gz'
DIGEST = '77a7cc357d060f31208d2c61bf845961ba55e23e92b85eb508d09421608e0337'
SIZE = 29417739
DIRECTORY = 'python-3.11.18-20261026-linux-musl'


def main(metadata, archive, destination, *, resume=False, reuse_verified=False):
    data = json.loads(metadata.read_text(encoding='utf-8'))
    choices = [a for a in data['assets'] if a['name'] == NAME]
    if (data['tag'] != '20261026' or len(choices) != 1
            or choices[0].get('digest') != 'sha256:'+DIGEST or choices[0]['size'] != SIZE):
        raise ValueError('python_runtime_upstream_metadata_changed')
    asset = choices[0]
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/astral-sh/python-build-standalone/releases/download/20261026/'):
        raise ValueError('python_runtime_download_source_invalid')
    prefix = archive.stat().st_size if archive.exists() else 0
    reuse = reuse_verified and prefix == SIZE
    if archive.exists() and not reuse and (not resume or not 0 < prefix < SIZE):
        raise ValueError('python_runtime_download_already_exists')
    deadline = time.monotonic() + 90
    h = sha256(); total = 0
    if prefix:
        with archive.open('rb') as stream:
            for block in iter(lambda:stream.read(1048576), b''): h.update(block); total += len(block)
    headers = {'User-Agent':'wsc-runtime-provision'}
    if prefix: headers['Range'] = 'bytes='+str(prefix)+'-'
    if not reuse:
        with urlopen(Request(url, headers=headers), timeout=20) as response:
            if prefix and (response.status != 206 or response.headers.get('Content-Range') != f'bytes {prefix}-{SIZE-1}/{SIZE}'):
                raise ValueError('python_runtime_resume_range_unverified')
            with archive.open('ab' if prefix else 'xb') as stream:
                while True:
                    if time.monotonic() > deadline: raise TimeoutError('python_runtime_download_deadline')
                    block = response.read(1048576)
                    if not block: break
                    total += len(block)
                    if total > SIZE: raise ValueError('python_runtime_download_size_exceeded')
                    h.update(block); stream.write(block)
    if total != SIZE or h.hexdigest() != DIGEST:
        raise ValueError('python_runtime_download_integrity_mismatch')
    if destination.name != DIRECTORY: raise ValueError('python_runtime_destination_unregistered')
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}; omitted = []; uncompressed = 0; seen = set(); case_names = set()
    with tarfile.open(archive, 'r:gz') as package:
        for member in package:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or '\\' in member.name
                    or not path.parts or path.parts[0] != 'python' or member.name in seen):
                raise ValueError('python_runtime_archive_member_invalid')
            seen.add(member.name)
            if member.isdir(): continue
            # Terminal databases have case-distinct names on Linux. They and
            # development headers/extra launchers are outside the task runtime.
            if not (member.name.startswith('python/lib/') or member.name == 'python/bin/python3.11'):
                continue
            if member.name.casefold() in case_names:
                raise ValueError('python_runtime_selected_case_collision')
            case_names.add(member.name.casefold())
            if member.issym():
                # No Windows symlink privilege or archive link traversal needed.
                omitted.append(dict(path=member.name, target=member.linkname)); continue
            if not member.isfile() or member.size > 67108864:
                raise ValueError('python_runtime_archive_type_invalid')
            uncompressed += member.size
            if uncompressed > 268435456: raise ValueError('python_runtime_archive_size_exceeded')
            relative = path.relative_to('python')
            target = destination/str(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = package.extractfile(member)
            digest = sha256(); written = 0
            with source, target.open('xb') as output:
                for block in iter(lambda:source.read(1048576), b''):
                    output.write(block); digest.update(block); written += len(block)
            if written != member.size: raise ValueError('python_runtime_member_truncated')
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
            manifest[str(relative)] = dict(bytes=written, sha256=digest.hexdigest())
    if 'bin/python3.11' not in manifest: raise ValueError('python_runtime_executable_missing')
    receipt = dict(version='3.11.18', release='20261026', platform='linux-musl-x86_64',
        source=url, package_sha256=DIGEST, package_bytes=SIZE, files=manifest,
        omitted_symlinks=omitted, executable='bin/python3.11',
        scope='Unmodified upstream interpreter/lib regular-file bytes; symlink aliases, share and headers omitted; no global installation')
    with (destination/'runtime-manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(dict(destination=str(destination), files=len(manifest), bytes=uncompressed,
        package_bytes=SIZE, package_sha256=DIGEST, omitted_symlinks=len(omitted))))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('metadata','archive','destination'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--reuse-verified', action='store_true')
    args = p.parse_args(); main(args.metadata, args.archive, args.destination, resume=args.resume, reuse_verified=args.reuse_verified)
