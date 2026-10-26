"""Materialize four independent runnable starters; never overwrite a prior start."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / 'benchmarks/application-five-task-v1'
OLD = ROOT / 'benchmarks/teamflow-long-v1/starter'

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8', newline='\n') as stream:
        stream.write(value)

shutil.copytree(OLD, SUITE / 'tasks/collaboration/starter')
seed = {
    'files': ('资源中心', '/api/files', {'name': 'README.txt', 'folder': '/', 'content_b64': 'V2VsY29tZQo=', 'tags': []}),
    'imports': ('导入工作台', '/api/records', {'customer': 'Legacy', 'amount': None, 'batch_id': 'legacy', 'source_line': None}),
    'booking': ('预约管理', '/api/bookings', {'resource_id': 'room-a', 'start': '2026-10-22T02:00:00Z', 'end': '2026-10-22T03:00:00Z', 'state': 'confirmed'}),
}
for task, (title, endpoint, payload) in seed.items():
    starter = SUITE / 'tasks' / task / 'starter'
    starter.mkdir()
    write(starter / 'backend/__init__.py', '')
    write(starter / 'backend/server.py', (OLD / 'backend/server.py').read_text(encoding='utf8'))
    # This is deliberately a v1 read-only prototype, not a reference solution.
    service = '''"""Runnable v1 read-only prototype. Persistent payloads are the migration input."""
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / DB_NAME
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO records VALUES(?,?)', ('welcome', json.dumps(SEED, ensure_ascii=False)))
            if db.execute('PRAGMA user_version').fetchone()[0] == 0:
                db.execute('PRAGMA user_version=1')

    def request(self, method, path, body, token):
        path = urlsplit(path).path
        if method == 'GET' and path == '/api/health':
            return 200, {'ok': True, 'schema': 1}
        if method == 'GET' and path == ENDPOINT:
            with sqlite3.connect(self.db) as db:
                items = [dict(id=row[0], **json.loads(row[1])) for row in db.execute('SELECT id,payload FROM records ORDER BY id')]
            return 200, {'items': items, 'next_cursor': None}
        return 404, {'error': 'not_found'}
'''
    service = ('DB_NAME = ' + repr(task + '.sqlite3') + '\nENDPOINT = ' + repr(endpoint) + '\nSEED = ' + repr(payload) + '\n' + service)
    write(starter / 'backend/service.py', service)
    write(starter / 'web/index.html', f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="stylesheet" href="/style.css"></head>
<body><header><h1>{title}</h1><p>本地旧版数据</p></header><main><button id="refresh">刷新</button><p role="status" id="notice"></p><section aria-label="记录" id="records"></section></main><script type="module" src="/app.js"></script></body></html>
''')
    write(starter / 'web/style.css', (OLD / 'web/style.css').read_text(encoding='utf8'))
    write(starter / 'web/app.js', f'''async function refresh() {{
  const notice = document.querySelector('#notice'); notice.textContent = '正在读取';
  try {{
    const response = await fetch('{endpoint}');
    if (!response.ok) throw new Error('读取失败 ' + response.status);
    const body = await response.json();
    document.querySelector('#records').replaceChildren(...body.items.map(item => {{
      const article = document.createElement('article');
      const title = document.createElement('h2'); title.textContent = item.name || item.customer || item.resource_id;
      const details = document.createElement('pre'); details.textContent = JSON.stringify(item, null, 2);
      article.append(title, details); return article;
    }})); notice.textContent = body.items.length + ' 条记录';
  }} catch (error) {{ notice.textContent = error.message; }}
}}
document.querySelector('#refresh').addEventListener('click', refresh);
refresh();
''')

for task in ('collaboration', 'files', 'imports', 'booking'):
    folder = SUITE / 'tasks' / task
    text = (folder / 'TASK.md').read_text(encoding='utf8')
    sections = text.split('\n## ')[1:]
    stages = []
    for index, section in enumerate(sections, 1):
        assert section.startswith(f'S{index} ')
        title, request = section.split('\n', 1)
        stages.append({'id': f'S{index}', 'title': title, 'request': request.strip()})
    assert len(stages) == 8
    write(folder / 'task.json', json.dumps(dict(
        kind='public_application_task_v1', id=task, starter='starter',
        common_contract='../../COMMON.md', task_contract='TASK.md', stages=stages,
        acceptance='../../acceptance/run.py', paired_repetitions=3,
        status='prepared_not_frozen', ready_to_launch=False,
        manual_required=['full_browser_workflows', 'themes_and_responsive_screenshots',
                         'keyboard_and_error_states', 'source_and_final_receipt_review'],
    ), ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'starters': 4, 'stages': 32, 'model_calls': 0}))
