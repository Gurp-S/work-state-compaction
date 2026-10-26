"""Opt-in typed native content: media bytes never become textual span input."""
import base64
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc.adapters.codex import CodexCheckpointAdapter,public_text
from wsc.contracts import Event,digest,encode
from wsc.content_archive import publish_object

TEXT={'input_text','output_text','text'}
MEDIA={'input_image','image','image_url','input_audio','audio','audio_url','input_file','file'}


def parts(item):
    if item.get('type')=='message':
        value=item.get('content')
    elif item.get('type') in {'custom_tool_call_output','function_call_output'}:
        value=item.get('output')
    else:
        return None
    if isinstance(value,list) and value and all(isinstance(part,dict) for part in value):
        kinds={part.get('type') for part in value}
        if kinds <= TEXT|MEDIA:
            return value
    return None


def text_projection(item):
    values=parts(item)
    if values is None:
        return public_text(item)
    values=[part['text'] for part in values if part.get('type') in TEXT and isinstance(part.get('text'),str)]
    return '\n'.join(values) if values else None


class TypedNativeAdapter(CodexCheckpointAdapter):
    def __init__(self,archive):
        self.archive=Path(archive).resolve()
        self.archive.mkdir(parents=True,exist_ok=True)

    def import_items(self,items,**kwargs):
        originals=super().import_items(items,**kwargs)
        result=[]
        for original,item in zip(originals,items):
            result.append(replace(original,text=text_projection(item)))
            for index,part in enumerate(parts(item) or []):
                if part.get('type') not in MEDIA:
                    continue
                info=dict(kind='native_media_archive',source_id=original.id,content_index=index,
                    native_content_type=part['type'],source_observed_at=original.observed_at,
                    availability='original_payload_only')
                uri=part.get('image_url')
                if isinstance(uri,dict):
                    uri=uri.get('url')
                if isinstance(uri,str) and uri.startswith('data:image/') and ';base64,' in uri:
                    header,data=uri.split(';base64,',1)
                    media_type=header[5:]
                    extension={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','image/gif':'.gif'}.get(media_type)
                    if extension:
                        raw=base64.b64decode(data,validate=True)
                        key=sha256(raw).hexdigest()
                        target=self.archive/(key+extension)
                        publish_object(target,raw)
                        info.update(availability='archived_bytes',media_type=media_type,path=str(target),
                            sha256=key,byte_length=len(raw))
                identity='native-media:'+digest(dict(source_id=original.id,index=index,descriptor=info))
                result.append(Event(identity,'observation',info,text=encode(info),observed_at=original.observed_at))
        return result


def dependencies(core):
    with core.store.connect() as db:
        rows=db.execute("SELECT data FROM events WHERE kind='observation'").fetchall()
    result=[]
    for row in rows:
        event=json.loads(row[0])
        value=event['payload']
        if (event['id'].startswith('native-media:') and value.get('kind')=='native_media_archive'
                and value.get('availability')=='archived_bytes'):
            result.append((value['path'],value['sha256']))
    return result
