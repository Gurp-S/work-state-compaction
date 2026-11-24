import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

from bench_llm import Chat  # noqa: E402

data = json.loads((ROOT / ".bench" / "Locomo-Plus" / "data" / "locomo10.json").read_text(encoding="utf-8"))
turns = data[0]["conversation"]["session_1"]
date = data[0]["conversation"]["session_1_date_time"]
chat = Chat()
system = """你是长期对话记忆提取器。输入是一段多人对话（含日期）。
提取对话中值得长期记住的事实：人物身份、关系、经历、偏好、计划、时间、地点、数字、情绪变化。
每条事实输出：{"entity": "人物或主题", "slot": "属性名", "value": "简洁完整的事实",
"topics": ["检索关键词"]}
entity 用对话中的真实姓名；同一事实用同一 slot。不要提取寒暄。没有可提取内容输出 []。"""
lines = "\n".join(f"{turn.get('speaker', '')}: {turn.get('text', '')}" for turn in turns)
text = chat.ask(system, f"日期：{date}\n对话：\n{lines}", max_tokens=900)
print(text[:1500])
