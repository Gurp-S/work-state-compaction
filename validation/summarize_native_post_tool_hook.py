"""Exact protocol assertions on scripted local-provider receipts, not an LLM judge."""
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    base = Path('D:/agent-task-runs')
    observations = []
    for version in (8, 9, 10):
        folder = base / f'wsc-runtime-hook-contract-20261029-v{version}'
        run = load(folder / 'result.json')
        assert run['exit_code'] == 0 and run['requests'] == 2 and run['hook_ran']
        hook = load(folder / 'hook-input.json')
        assert hook['hook_event_name'] == 'PostToolUse' and hook['tool_name'] == 'Bash'
        assert hook['tool_response'] == 'WSC_RAW_RESULT_FIXTURE\r\n'
        outputs = [item for item in load(folder / 'request-2.json')['input']
                   if item.get('call_id') == 'call_fixture' and item['type'].endswith('_output')]
        assert len(outputs) == 1
        output = outputs[0]
        if version == 8:
            values = [json.loads(block['text']) for block in output['output']
                      if block['type'] == 'input_text' and block['text'].startswith('{')]
            assert len(values) == 1
            assert values[0]['promise_resolved'] is True
            assert values[0]['result']['exit_code'] == 0
            assert values[0]['result']['output'] == hook['tool_response']
            replaced = False
        else:
            assert output['type'] == 'function_call_output'
            assert output['output'] == 'WSC_HOOK_REPLACEMENT_FIXTURE'
            assert output['call_id'] == hook['tool_use_id']
            replaced = True
        commands = [row['item'] for line in (folder / 'stdout.jsonl').read_text().splitlines()
                    if (row := json.loads(line))['type'] == 'item.completed'
                    and row['item']['type'] == 'command_execution']
        assert len(commands) == 1
        assert commands[0]['exit_code'] == (1 if version == 10 else 0)
        observations.append(dict(version=version, fixture=str(folder),
            next_request_replaced=replaced, code_mode=version == 8,
            command_exit_code=commands[0]['exit_code'],
            hook_response_type=type(hook['tool_response']).__name__,
            exit_code_in_hook_input='exit_code' in hook, model_calls=0))
    result = dict(kind='native_scripted_protocol_qualification', observations=observations,
        ordinary_text_replacement_verified=True, code_mode_transparent_replacement_verified=False,
        failure_metadata_preservation_verified=False, model_raw_recovery_verified=False,
        paid_denoise_admitted=False, global_configuration_changed=False,
        exact_protocol_checks_passed=True, native_model_quality_test=False,
        limitations=['scripted local provider', 'fallback model metadata',
                     'isolated CODEX_HOME', 'danger-full-access fixture sandbox',
                     'raw hook payload persisted; no model recovery exercised'])
    target = base / 'wsc-runtime-denoise-admission-20261029-v1/native-hook-qualification.json'
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
