"""Read archived media dependencies without sharing orchestration variables."""
from pathlib import Path
from native_evidence import read


def dependencies(package):
    result=[]
    for source_id,locator in package['evidence'].items():
        if not source_id.startswith('native-media:'):
            continue
        value=read(Path(locator['file_path']))
        if value.get('kind')=='native_media_archive' and value.get('availability')=='archived_bytes':
            result.append((value['path'],value['sha256']))
    return result
