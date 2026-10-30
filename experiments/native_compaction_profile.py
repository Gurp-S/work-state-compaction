"""Explicit common-host remote-v2 profile and wire admission, no summarizer."""
from native_provider_frames import loads

PROFILE='native_remote_v2_http_v1'


def settings(profile,*,provider='wsc_bridge'):
    if profile is None:return []
    if profile!=PROFILE or provider not in ('wsc_bridge','wsc_fixture'):
        raise ValueError('native_compaction_profile_unregistered')
    return ['model_providers.'+provider+'.capabilities.remote_compaction="v2"']


def admit_request(value):
    if type(value) is not dict or type(value.get('input')) is not list:
        raise ValueError('native_remote_compaction_request_invalid')
    metadata=value.get('client_metadata',{})
    if type(metadata) is not dict:raise ValueError('native_compaction_metadata_invalid')
    try:turn=loads(metadata.get('x-codex-turn-metadata','{}'))
    except (ValueError,TypeError):raise ValueError('native_compaction_metadata_invalid') from None
    triggers=[item for item in value['input'] if type(item) is dict and item.get('type')=='compaction_trigger']
    if type(turn) is not dict or turn.get('request_kind')!='compaction' or len(triggers)!=1:
        raise ValueError('native_remote_compaction_trigger_unverified')
    return dict(profile=PROFILE,request_kind='compaction',trigger_count=1,
        scope='Request construction only; no evidence that compaction completed')
