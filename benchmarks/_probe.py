import sys
sys.path.insert(0, "benchmarks")
from bench_llm import Chat

chat = Chat()
print(chat.ask("只输出 JSON", '输出 {"ok": true}'))
print("calls", chat.calls, "tokens", chat.prompt_tokens, chat.completion_tokens)
