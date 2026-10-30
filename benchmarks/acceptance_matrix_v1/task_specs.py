"""Authored task policies and synthetic histories, never model-scored answers.

Only starter files and public history enter a model workspace. Reference code,
private assertion answers and acceptance implementation remain coordinator-side.
An actual last-state-only model control is still required to qualify each task.
"""
from copy import deepcopy
import json
from pathlib import Path
from hashlib import sha256

from .evidence import seal


ROOT = Path(__file__).resolve().parent
SPECS = {
    'T1': dict(folder='t1_retry', entry='retry_client.py', callable='run_batch',
        latest=dict(revision=2, accepted_methods=['GET', 'POST'], retry_statuses=[429, 503],
            success_statuses=[200, 201, 202, 204], attempts='positive_integer_total_including_first',
            default_max_attempts=3, attempt_numbers='one_based', timeout='retry_within_total_limit',
            other_exceptions='propagate_without_retry', identity=['tenant', 'id'],
            duplicate_jobs='coalesce_exact_full_job', conflicts='reject_entire_batch_before_send',
            post_key='nonempty_idempotency_key', payload='same_original_value_each_attempt_caller_unchanged',
            terminal_http='failed_row_then_continue_batch',
            output_fields=['tenant', 'id', 'state', 'status', 'value', 'attempts']),
        old=dict(revision=1, retry_statuses=[500, 503], success_statuses=[200],
                 attempts='additional_retries', identity=['id'], duplicate_jobs='send_each'),
        assertion_fields=['revision', 'retry_statuses', 'identity', 'attempts', 'payload'],
        constraints=['retry-boundary', 'request-integrity', 'tenant-identity', 'no-partial-invalid-batch'],
        request='修复 retry_client.py 的批量请求重试实现。接口仍为 run_batch(jobs, send, max_attempts=3)，以此前契约注册表中最高 revision 为准；修复公开失败并完成契约行为。返回结构化 assertions，按指定字段报告所用契约值及 source_id/field_path。'),
    'T3': dict(folder='t3_migration', entry='migrate.py', callable='migrate',
        latest=dict(revision=2, target_schema_version=3, supported_versions=[1, 2, 3],
            layouts={'1': ['id', 'tenant', 'title', 'deleted'], '2': ['id', 'workspace_id', 'title', 'archived']},
            final_columns=['id', 'workspace_id', 'title', 'archived', 'row_version'],
            initial_row_version=1, identity='preserve_id_workspace_title_exactly',
            deleted_rows='preserve_as_archived', unique_active=['workspace_id', 'title'],
            duplicate_active_titles='smallest_text_id_remains_active_others_archived',
            replay='no_state_or_row_version_reset', transaction='savepoint_preserves_caller_transaction',
            failure='rollback_migration_only', unsupported_or_ambiguous_version='reject_unchanged',
            staging_collision='reject_without_deleting_existing_table',
            declared_v3='reject_incomplete_columns_without_mutation'),
        old=dict(revision=1, target_schema_version=2, deleted_rows='delete', unique_active=['title'],
                 transaction='commit_everything'),
        assertion_fields=['revision', 'deleted_rows', 'unique_active', 'transaction', 'replay'],
        constraints=['history-preservation', 'workspace-identity', 'no-state-reset', 'version-boundary',
                     'transaction-atomicity', 'transaction-ownership', 'unrelated-data-preservation'],
        request='修复 migrate.py，将已有项目数据库按此前最新契约升级。接口为 migrate(connection)，调用方拥有事务；旧决策已在历史中变更。保留公开测试并完成迁移、重放和失败恢复。返回结构化 assertions，按指定字段报告所用契约值及 source_id/field_path。'),
    'T2': dict(folder='t2_api', entry='api.ts', callable='listUsage', language='typescript',
        task_goal='迁移分页查询API签名并更新所有调用方，当前工作树仍是baseline-v1，候选接口草案不是已提交实现',
        artifact_paths=['api.ts', 'cli.ts', 'dashboard.ts', 'exporter.ts', 'worker.ts'],
        public_check='node <registered_tsc> --strict --noEmit --target ES2020 --module commonjs --lib ES2020,DOM api.ts cli.ts dashboard.ts exporter.ts worker.ts smoke.ts',
        latest=dict(revision=2, signature='listUsage(rows, query): Page',
            query_fields=['tenant', 'model', 'includeArchived', 'pageSize', 'after'],
            model_identity=['provider', 'name'], default_page_size=2, max_page_size=100,
            default_include_archived=False, ordering='ascending_id',
            cursor='reject_unless_in_the_current_scoped_filtered_query', input_mutation=False,
            caller_modes={'cli': 'exact_pair_active_first_page', 'dashboard': 'exact_pair_including_archived_first_page',
                          'exporter': 'exact_pair_active_all_pages', 'worker': 'all_models_including_archived_first_page'},
            return_fields=['items', 'nextCursor'], typescript_strict=True,
            source_budget_bytes=1048576, source_budget_files=256),
        old=dict(revision=1, signature='listUsage(rows, tenant, model): Row[]',
                 model_identity=['name'], caller_modes='all_callers_unpaged_same_filter'),
        assertion_fields=['revision', 'model_identity', 'default_page_size', 'caller_modes', 'cursor'],
        constraints=['public-api-shape', 'provider-identity', 'tenant-boundary', 'query-validation',
                     'input-integrity', 'export-completeness'],
        request='将 api.ts 的 listUsage 迁移到历史中已确认的Query/Page接口，并更新CLI、dashboard、exporter、worker所有调用方。以最新契约而非旧文件草案为准；严格类型检查和行为验收均需通过。保留公开smoke。返回结构化 assertions，报告指定契约字段及source_id/field_path。'),
    'T4': dict(folder='t4_ui', entry='app.js', callable='mountUsage', language='browser',
        task_goal='开发Usage desk交互界面，工作树和baseline截图仅代表旧版本，按历史最新配置修复',
        artifact_paths=['index.html', 'app.js', 'style.css', 'config.json', 'data.json', 'baseline.png'],
        public_check='Registered browser smoke: load index.html over HTTP, heading Usage desk, 3 data rows, beta / same cost cell Unknown',
        latest=dict(revision=2, currency='CNY', model_identity=['provider', 'model'],
            filter_scope='loaded_rows_only', missing_cost='Unknown',
            refresh_failure='retain_rows_mark_stale', request_race='latest_request_wins',
            mount='window.mountUsage(root,config,initial,load): {destroy()}',
            input='initial/load resolve to {kind:ready,rows:[{id,provider,model,tokens,cost_cny,price_state}]} or {kind:missing}',
            input_domain='Unique string row IDs; tokens nonnegative integer or null; cost_cny nonnegative finite number or null; price_state priced/missing/unpriced; missing/unpriced imply null cost',
            filter='select accessible name Model; option values JSON.stringify([provider,model]); empty value All models; missing selected pair after refresh resets to All',
            row='tbody tr data-row-id=id; three td: provider + space/slash/space + model, tokens, cost CNY; text rendered literally',
            value_states={'zero_tokens': '0', 'zero_cost': '0.00', 'missing_tokens': 'Unknown',
                          'missing_cost': 'Unknown', 'unpriced_cost': 'Unpriced', 'priced_cost': 'two decimal places'},
            total='output accessible name Cost total; visible rows only; any null cost => Incomplete, otherwise sum with two decimals',
            status={'ready': 'Ready', 'empty': 'No matching rows', 'missing': 'Data unavailable',
                    'failed_refresh': 'Stale: refresh failed'},
            controls='h1 Usage desk; button Refresh calls load; role=status text; exact visible text Filter scope: loaded rows only',
            lifecycle='destroy empties root; pending requests cannot write after destroy',
            viewport='390x720 and 1024x720, controls visible, no horizontal page overflow',
            entrypoint='index.html fetches config.json/data.json and mounts app; current config retains latest six policy fields plus revision'),
        old=dict(revision=1, model_identity=['model'], filter_scope='server', missing_cost='zero',
                 refresh_failure='clear_data', request_race='last_completion_wins'),
        assertion_fields=['revision', 'model_identity', 'filter_scope', 'refresh_failure', 'request_race'],
        constraints=['entrypoint', 'config-revision', 'provider-identity', 'value-states', 'aggregate-scope',
                     'refresh-integrity', 'request-order', 'filter-validity', 'lifecycle', 'data-integrity', 'visible-scope'],
        request='修复Usage desk，保留index.html入口及window.mountUsage(root,config,initial,load)接口。config.json更新至历史最新配置，完成筛选、状态和刷新交互。baseline.png仅是旧版实测截图。返回结构化 assertions，报告指定契约字段及source_id/field_path。'),
    'T5': dict(folder='t5_pipeline', entry='pipeline.py', callable='run',
        task_goal='实现发票CSV到规范化数据、租户汇总、manifest的多阶段管道，历史中间产物不代表当前代码已通过',
        latest=dict(revision=2, entry='run(source, output): manifest', format='invoice.pipeline/2',
            input_header=['tenant', 'invoice', 'amount'], decoding='strict_utf8',
            amount_pattern=r'-?[0-9]+(?:\.[0-9]{1,2})?', cents='exact_integer_not_float',
            identity=['tenant', 'invoice'], identity_whitespace='strip',
            duplicates='coalesce_equal_cent_values_reject_conflicts',
            normalized_fields=['tenant', 'invoice', 'cents'], normalized_order=['tenant', 'invoice'],
            totals_fields=['tenant', 'invoice_count', 'total_cents'], totals_order=['tenant'],
            source_digest_basis='original_input_bytes', stages=['normalized', 'totals'],
            stage_links='totals.from_sha256_equals_normalized.sha256',
            publication='one_manifest_commit_referencing_actual_immutable_stage_files',
            replay='identical_manifest_and_stage_bytes', invalid_input='ValueError_without_changing_published_commit',
            existing_stage_corruption='reject_without_overwrite', input_mutation=False),
        old=dict(revision=1, format='invoice.pipeline/1', decoding='replacement_utf8',
                 cents='floating_total', identity=['invoice'], publication='overwrite_single_manifest'),
        assertion_fields=['revision', 'decoding', 'identity', 'source_digest_basis', 'stage_links'],
        constraints=['stage-lineage', 'invoice-identity', 'no-invalid-publication', 'source-fidelity',
                     'history-preservation', 'no-conflict-overwrite'],
        request='修复 pipeline.py，实现已确认的CSV、规范化、汇总、manifest交接。保留run(source, output)入口和公开smoke，引用真实落盘产物，旧阶段结果不能当当前验证。返回结构化 assertions，报告指定契约字段及source_id/field_path。'),
}


def message(role, value):
    text = value if type(value) is str else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return dict(type='message', role=role, content=[dict(type='input_text' if role == 'user' else 'output_text', text=text)])


def build_task(task, *, public_failure_log, noise=20, screenshot=None):
    if task not in SPECS or type(noise) is not int or not 0 <= noise <= 10000:
        raise ValueError('task_spec_invalid')
    spec = SPECS[task]
    sources = {}
    prefix = [message('user', dict(record_type='fixture.task/1', task=task,
        task_goal=spec.get('task_goal', '修复批量请求客户端的失败测试与契约行为' if task == 'T1' else '实现项目数据库迁移及重放、事务恢复'),
        artifact_paths=spec.get('artifact_paths', [spec['entry']]),
        authority='Contract registry records define the API policy; greatest revision is current. Assistant hypotheses are not registry updates.',
        input_identity='Authored benchmark history, including paired historical fixture observations.'))]
    def observation(identity, value):
        source = dict(source_id=identity, **deepcopy(value))
        sources[identity] = dict(data=source, sha256=seal(source))
        call = identity.replace('/', '_')
        prefix.append(dict(type='function_call', call_id=call, name='fixture_observe',
                           arguments=json.dumps({'fixture_source': identity})))
        prefix.append(dict(type='function_call_output', call_id=call,
                           output=json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':'))))
    old_id, new_id = task+'/policy/r1', task+'/policy/r2'
    observation(old_id, dict(record_type='contract.registry/1', policy=spec['old']))
    if task == 'T4':
        observation(task+'/configuration/catalog', dict(record_type='fixture.configuration_catalog/1',
            unrelated_widgets=[dict(id='widget-'+str(i), enabled=i % 3 == 0,
                columns=['label', 'description', 'owner', 'last_seen'],
                description='Independent dashboard widget settings, not Usage desk policy') for i in range(180)]))
        if screenshot is not None:
            observation(task+'/screenshot/baseline', dict(record_type='fixture.screenshot/1',
                path='baseline.png', source_version='baseline-v1', current_verification=False, **screenshot))
    if task == 'T2':
        raw = (ROOT/'tasks/t2_api/starter/api.ts').read_bytes()
        observation(task+'/file/api/v1', dict(record_type='fixture.file_version/1', path='api.ts',
            version='baseline-v1', current_worktree=True, content_sha256=sha256(raw).hexdigest(), text=raw.decode('utf-8')))
    for index in range(noise):
        observation(task+f'/log/{index:04d}', dict(record_type='fixture.replayed_public_test_log/1',
            replay_index=index, log=public_failure_log, scope='Repeated observation of one captured public smoke failure, not a new executed attempt or a model trajectory.'))
    observation(new_id, dict(record_type='contract.registry/1', policy=spec['latest']))
    if task == 'T2':
        prototype = "export function listUsage(rows: Row[], query: Query): Page { return { items: rows, nextCursor: null }; }"
        observation(task+'/file/api/v2-prototype', dict(record_type='fixture.file_version/1', path='api.ts',
            version='unmerged-prototype-v2', current_worktree=False,
            content_sha256=sha256(prototype.encode('utf-8')).hexdigest(), text=prototype))
    if task == 'T5':
        observation(task+'/artifact/prior', dict(record_type='fixture.prior_stage/1', path='manifest.json',
            format='invoice.pipeline/1', source_version='baseline-v1', current_verification=False))
    prefix.append(message('assistant', dict(record_type='fixture.assistant_hypothesis/1',
        proposed_old_policy=spec['old'], status='unverified_hypothesis_not_registry_update')))
    request = spec['request'] + '\nAssertion IDs: ' + ', '.join(spec['assertion_fields'])
    public = dict(schema='wsc.acceptance.task_fixture/1', task=task, prefix=prefix,
                  request=request, artifact_paths=spec.get('artifact_paths', [spec['entry']]), constraints=spec['constraints'],
                  public_check=spec.get('public_check', 'py -3.11 -B -m unittest discover -s . -p test_smoke.py -v'),
                  history_dependency_qualified=False, synthetic_history=True)
    private = dict(public_sha256=seal(public), sources=sources,
                   expected_assertions={key: deepcopy(spec['latest'][key]) for key in spec['assertion_fields']},
                   latest_source_id=new_id, scope='Private expected values and source map; never adapter input.')
    return public, private
