import json
import sys
from pathlib import Path

ROOT = Path(r"D:\lea\XenYon code\wsc")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))
from bench_llm import Chat  # noqa: E402
import csm_locomo_plus as locomo  # noqa: E402

data = json.loads((ROOT / ".bench" / "Locomo-Plus" / "data" / "locomo10.json").read_text(encoding="utf-8"))
chat = Chat()
name, date, turns = locomo.sessions_of(data[0])[0]
for start in (0, 6):
    items = locomo.extract_session(chat, date, turns[start:start + 6])
    print(start, len(items), [(i["entity"], i["slot"], i["value"][:40]) for i in items[:4]])
