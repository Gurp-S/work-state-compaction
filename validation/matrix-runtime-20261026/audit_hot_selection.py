"""Measure the archived selected information; no semantic trimming or model calls."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save
from native_indexed_checkpoint import expand_working_state

AREA = Path('D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1')
package = read(AREA / 'package.json')
metadata = read(package['adapter']['projection_evidence']['file_path'])
index = next(i for i, item in enumerate(package['items']) if item.get('role') == 'assistant'
    and item.get('content') and 'wsc.indexed_sections/1' in item['content'][0].get('text', ''))
facts = expand_working_state(package['items'][index]['content'][0]['text'], metadata)
sizes, counts = Counter(), Counter()
for row in metadata['sections']:
    sizes[row['kind']] += row['bytes']; counts[row['kind']] += 1
native_messages = [item for n, item in enumerate(package['items']) if n != index]
message_bytes = sum(len(part.get('text', '').encode()) for item in native_messages for part in item.get('content', []))
observations = facts['observations']
covered = [row for row in observations if 'inline_coverage' in row]
result = dict(section_text_bytes=dict(sizes), section_counts=dict(counts),
    retained_native_message_text_bytes=message_bytes, retained_native_message_count=len(native_messages),
    excerpt_observations=len(observations), already_inline_covered_excerpt_observations=len(covered),
    model_record_count=len(facts['model_records']), clue_count=len(facts['clues']),
    selected_historical_sources=[dict(kind=row['kind'], source_id=row['source']['source_id'],
        text_bytes=len(row['text'].encode())) for row in facts['historical_excerpts']],
    model_calls=0, scope='Literal byte and coverage measurement; whole-source and span choices are model-authored, not inferred semantic relevance',
    caveat='Inline coverage avoids duplicate transmission. This audit alone does not prove that any selected whole source is unnecessary.')
save(AREA / 'hot-selection-audit.json', result)
print({key: result[key] for key in ('section_text_bytes', 'retained_native_message_text_bytes',
    'excerpt_observations', 'already_inline_covered_excerpt_observations', 'model_record_count', 'clue_count')})
