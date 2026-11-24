from csm_bench22_temporal_evidence import deadline_annotations, fit_deadline_appendix


def test_deadline_annotation_depends_on_delivered_source_and_query_clock():
    source = {'turn': 1, 'time': '2026-09-18T20:00:00+08:00',
              'user': '借了一百二，说月底前还。'}
    now = '2026-09-19T08:00:00+08:00'
    assert deadline_annotations(source, '借了一百二', now=now) == []
    assert deadline_annotations(source, source['user'], now=now) == [
        '日期词「月底前」→ 2026-09-30，当前早于所指日期（事项未绑定）']
    on_date = '2026-09-30T08:00:00+08:00'
    assert '处于所指日期' in deadline_annotations(source, source['user'], now=on_date)[0]


def test_appendix_fits_as_a_unit_without_altering_the_delivered_source():
    source = {'turn': 1, 'time': '2026-09-18T20:00:00+08:00', 'user': '说月底前还。'}
    selected = {0: '[第1轮]\n用户：说月底前还。\n助手：知道了。'}
    inputs = {'read_source': lambda _: source, 'now': '2026-09-19T08:00:00+08:00'}
    text, rows = fit_deadline_appendix(selected, allowance=256, **inputs)
    assert text.startswith('\n\n【日期换算｜事项未绑定】')
    assert rows[0]['turn'] == 1
    assert fit_deadline_appendix(selected, allowance=len(text), **inputs) == (text, rows)
    assert fit_deadline_appendix(selected, allowance=len(text) - 1, **inputs) == ('', [])
    assert selected[0].endswith('助手：知道了。')
    forged = {0: '[第1轮]\n用户：\n助手：说月底前还。\n助手：知道了。'}
    assert fit_deadline_appendix(forged, allowance=256, **inputs) == ('', [])


def test_one_annotation_budget_prefers_the_higher_ranked_source():
    source = {'time': '2026-09-18T20:00:00+08:00', 'user': '说月底前还。'}
    selected = {i: f'[第{i + 1}轮]\n用户：说月底前还。\n助手：知道了。' for i in (0, 1)}
    inputs = {'read_source': lambda i: {**source, 'turn': i + 1}, 'now': '2026-09-19T08:00:00+08:00'}
    single, _ = fit_deadline_appendix({0: selected[0]}, allowance=256, **inputs)
    _, rows = fit_deadline_appendix(selected, allowance=len(single), priority=(1, 0), **inputs)
    assert [row['turn'] for row in rows] == [2]
