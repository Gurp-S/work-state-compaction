"""Minimal OpenAI-compatible chat client for the benchmark adapters (no third-party SDK).

Configuration comes from the environment, so the same adapters run against the local
WorkBuddy gateway or any other OpenAI-compatible endpoint:
    CSM_BENCH_BASE_URL   default http://127.0.0.1:8788/v1
    CSM_BENCH_API_KEY    fallback: DEEPSEEK_API_KEY from the DSH credentials file
    CSM_BENCH_MODEL      default deepseek-v4.1-flash
    CSM_BENCH_TRANSPORT_POLICY  legacy (default), text-only, or purpose-routed
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
import yaml
from bench_request_policy import selected_policy, configure, validate_text_envelope

BASE_URL = os.environ.get("CSM_BENCH_BASE_URL", "http://127.0.0.1:8788/v1").rstrip("/")
MODEL = os.environ.get("CSM_BENCH_MODEL", "deepseek-v4.1-flash")


def _key() -> str:
    key = os.environ.get("CSM_BENCH_API_KEY")
    if key:
        return key
    path = Path.home() / ".dsh" / ".credentials.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    key = data["refs"].get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("no CSM_BENCH_API_KEY and no DEEPSEEK_API_KEY in DSH credentials")
    return key


class Chat:
    def __init__(self, temperature: float = 0.0, max_tokens: int = 1024):
        self.transport_policy = selected_policy()
        self.key = _key()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tool_exchanges = []

    def exchange(self, messages, *, tools, tool_choice, max_tokens=2048):
        """Explicit nonstream tool exchange, independent of legacy ask policy."""
        from bench_tool_transport import exchange
        return exchange(self, messages, tools=tools, tool_choice=tool_choice,
                        max_tokens=max_tokens, base_url=BASE_URL, model=MODEL)

    def ask(self, system: str, user: str, *, max_tokens: int | None = None,
            purpose: str = 'answer') -> str:
        payload = {"model": MODEL, "temperature": self.temperature,
                   "max_tokens": max_tokens or self.max_tokens,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        payload = configure(payload, self.transport_policy, purpose)
        last_status = None
        attempts = 4 if self.transport_policy == 'legacy' else 1
        for attempt in range(attempts):
            try:
                response = requests.post(f"{BASE_URL}/chat/completions",
                                         headers={"Authorization": f"Bearer {self.key}"},
                                         json=payload, timeout=180)
                last_status = response.status_code
                if response.status_code in (429, 502, 503, 504):
                    if self.transport_policy != 'legacy' and attempt == attempts - 1:
                        response.raise_for_status()
                    time.sleep(2 ** attempt)
                    continue
                if response.status_code == 401:
                    # The local gateway accepts its own panel key, not the remote provider's;
                    # saying so beats four silent retries that end in a bare "Unauthorized".
                    raise RuntimeError(
                        f"401 from {BASE_URL}: the gateway key is refs.WD_API_KEY in "
                        f"~/.dsh/.credentials.yaml (set CSM_BENCH_API_KEY); the DEEPSEEK_API_KEY "
                        f"fallback is rejected by a local gateway.")
                response.raise_for_status()
                data = response.json()
                self.calls += 1
                usage = data.get("usage", {})
                self.prompt_tokens += usage.get("prompt_tokens", 0)
                self.completion_tokens += usage.get("completion_tokens", 0)
                if self.transport_policy != 'legacy':
                    return validate_text_envelope(data,
                        allow_reasoning=self.transport_policy == 'purpose-routed' and purpose != 'format')
                content = data["choices"][0]["message"]["content"] or ""
                if not content.strip() and attempt < attempts - 1:
                    time.sleep(1 + attempt)
                    continue
                return content
            except (requests.RequestException, KeyError, ValueError):
                if attempt == attempts - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError(f"gateway returned {last_status} on all {attempts} attempts")

    def ask_json(self, system: str, user: str, *, max_tokens: int | None = None,
                 purpose: str = 'extract'):
        text = self.ask(system, user, max_tokens=max_tokens, purpose=purpose).strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        # 先取位置最靠前的括号：数组只有一个元素时，先试 "{" 会把 [{...}] 截成 {...}，
        # 调用方拿到的就不是列表了。
        openers = [pair for pair in (("[", "]"), ("{", "}")) if text.find(pair[0]) != -1]
        openers.sort(key=lambda pair: text.find(pair[0]))
        for opener, closer in openers:
            start, end = text.find(opener), text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue
        raise ValueError(f"no JSON in model output: {text[:200]}")
