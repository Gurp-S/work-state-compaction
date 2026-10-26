"""Explicit opt-in host settings and transport-only bootstrap normalization."""
from copy import deepcopy
import json
from pathlib import Path


FEATURE_OVERRIDES = {'recommended_plugins': False, 'tool_suggest': False}


def settings(registration):
    overrides = registration.get('host_feature_overrides', {})
    if overrides and overrides != FEATURE_OVERRIDES:
        raise ValueError('application_host_feature_overrides_unregistered')
    result = ['features.multi_agent=false',
            'model_reasoning_effort=' + json.dumps(registration['effort'])] + [
                'features.' + key + '=false' for key in sorted(overrides)]
    if registration.get('browser_cache'):
        root=Path(registration['workspace']).resolve()
        cache=Path(registration['browser_cache']).resolve()
        if not cache.is_relative_to(root) or cache==root or not cache.is_dir():
            raise ValueError('application_browser_cache_not_private')
        result.append('shell_environment_policy.set.PLAYWRIGHT_BROWSERS_PATH='+json.dumps(str(cache)))
    if 'native_c_auto_compaction' in registration:
        from native_c_auto_compaction import startup_flags
        result.extend(startup_flags(registration))
    return result


def normalize(value, workspace):
    workspace = str(Path(workspace).resolve())
    if isinstance(value, str):
        for spelling in (json.dumps(workspace)[1:-1], workspace, workspace.replace('\\', '/')):
            value = value.replace(spelling, '$REGISTERED_WORKSPACE')
        return value
    if isinstance(value, dict):
        return {key: normalize(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item, workspace) for item in value]
    return value


def bootstrap_items(items, workspace):
    items = deepcopy(items)
    for item in items:
        if item.get('type') in {'message', 'additional_tools'}:
            item.pop('id', None)
        if item.get('type') == 'message':
            item.pop('internal_chat_message_metadata_passthrough', None)
    return normalize(items, workspace)
