import sys
from pathlib import Path

ROOT = Path(r"D:\lea\XenYon code\wsc")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / ".bench" / "memory-system-benchmark" / "demo"))
from bench_llm import Chat  # noqa: E402
import csm_public_exam as exam  # noqa: E402

chat = Chat()
_, histories = exam.read_exam.load()
rows = histories[list(histories)[0]][0]
for number in (29, 53, 55, 69, 137, 163, 187, 211):
    turn = rows[number - 1]
    items = exam.extract(chat, turn, [])
    print(number, turn["用户消息"][:40], "->", [(i["entity"], i["slot"], i["value"][:40]) for i in items])
