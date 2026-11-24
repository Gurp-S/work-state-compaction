"""Small write-time batches for the opt-in flat Revision benchmark arm."""
import json

from csm_bench22_flat_revision import FlatRevisionBench22
from csm_bench22_state import parse_model_json
from wsc.csm import Event


class BatchRevisionBench22(FlatRevisionBench22):
    def __init__(self, gateway, *, json_output=True, focus_state=False, state_embedder=None):
        super().__init__(gateway, focus_state=focus_state, state_embedder=state_embedder)
        self.json_output = json_output

    def _batch(self, events, candidates):
        schema = ('输入是按顺序排列的用户原文。提炼后续可用的状态，包括偏好、日期、属性、'
                  '行为及触发条件、进度、承诺和变更。每个变化只依据对应原文，保留数值、单位、否定和范围。'
                  '已有同一实体、属性、范围时 target 为候选 memory_id。批内首次出现或同一属性再次变化时，'
                  '复用原文实体名、slot 和 contexts。第一人称本人使用 "source.speaker"。'
                  'contexts 是字符串数组，元素仅为稳定的对象名或适用范围。金额、数量、时间、进度等可变值只在 value。'
                  '同一属性的后续变化沿用 slot，即使原文换了一种说法。'
                  '输出一个 JSON 对象，键为来源 id，值为没有变化时的 []，或如下格式的增量数组：'
                  '[{"target":null,"new_entity":"source.speaker","slot":"属性","contexts":["对象名"],'
                  '"value":"本轮观察到的值","confidence":0.9}]。')
        payload = {'sources': [{'id': event.id, 'text': event.payload['user'],
                                'time': event.observed_at, 'speaker': event.payload['speaker']}
                               for event in events], 'entities': candidates}
        messages = [
            {'role': 'system', 'content': schema},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
        ]
        options = {'temperature': 0, 'thinking': {'type': 'disabled'}}
        if self.json_output:
            options['response_format'] = {'type': 'json_object'}
        choice, = self.gateway.chat('deepseek-v4.1-flash', messages, 'ingest', 'state-revision-batch',
                                    max_tokens=1536, **options)['choices']
        if choice['finish_reason'] == 'length':
            choice, = self.gateway.chat('deepseek-v4.1-flash', messages, 'ingest', 'state-revision-batch',
                                        max_tokens=3072, **options)['choices']
        if choice['finish_reason'] != 'stop':
            raise ValueError('revision_batch_unfinished')
        return parse_model_json(choice['message']['content'])

    def ingest_batch(self, turns):
        sources = [self._source_payload(turn) for turn in turns]
        start = self.mark() + 1
        if [row['turn'] for row in sources] != list(range(start, start + len(sources))):
            raise ValueError('non_contiguous_batch')
        events = [Event(f"chat/{row['turn']}", 'chat', {**row, 'speaker': '用户'}, observed_at=row['time'])
                  for row in sources]
        self.writer.consume_batch(events, self._batch)
        for source in sources:
            self._index_source(source)
