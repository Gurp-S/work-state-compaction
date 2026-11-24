"""Real endpoint pricing: cached input, uncached input and output.

Prices are yuan per million tokens (user-provided, 2026-11-18):

    cached input   0.02
    uncached input 1.00
    output         4.00

Cost per compression is split from ``prompt_tokens`` and
``prompt_tokens_details.cached_tokens``; nothing is estimated.
"""
from __future__ import annotations

PRICES = {'cached_input': 0.02, 'uncached_input': 1.00, 'output': 4.00}
MILLION = 1_000_000


def split(usage: dict) -> dict:
    prompt = int((usage or {}).get('prompt_tokens') or 0)
    details = (usage or {}).get('prompt_tokens_details') or {}
    cached = int(details.get('cached_tokens') or 0)
    cached = max(0, min(cached, prompt))
    completion = int((usage or {}).get('completion_tokens') or 0)
    return {'cached_input': cached, 'uncached_input': prompt - cached, 'output': completion}


def cost_of(usage: dict) -> float:
    parts = split(usage)
    return round(sum(parts[key] * PRICES[key] for key in PRICES) / MILLION, 6)


def cost_from_tokens(prompt: int, completion: int, cached: int = 0) -> float:
    """Cost for aggregates that only kept prompt/completion totals."""
    prompt, completion = int(prompt or 0), int(completion or 0)
    cached = max(0, min(int(cached or 0), prompt))
    return round(((prompt - cached) * PRICES['uncached_input']
                  + cached * PRICES['cached_input']
                  + completion * PRICES['output']) / MILLION, 6)


def add(target: dict, usage: dict) -> dict:
    """Accumulate split tokens and cost into an existing counter."""
    parts = split(usage)
    prompt = int((usage or {}).get('prompt_tokens') or 0)
    completion = int((usage or {}).get('completion_tokens') or 0)
    details = (usage or {}).get('completion_tokens_details') or {}
    target['prompt_tokens'] = target.get('prompt_tokens', 0) + prompt
    target['completion_tokens'] = target.get('completion_tokens', 0) + completion
    target['reasoning_tokens'] = (target.get('reasoning_tokens', 0)
                                  + int(details.get('reasoning_tokens') or 0))
    target['cached_input_tokens'] = target.get('cached_input_tokens', 0) + parts['cached_input']
    target['uncached_input_tokens'] = target.get('uncached_input_tokens', 0) + parts['uncached_input']
    target['output_tokens'] = target.get('output_tokens', 0) + parts['output']
    target['cost'] = round(target.get('cost', 0.0) + cost_of(usage), 6)
    return target


def empty() -> dict:
    return {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
            'reasoning_tokens': 0,
            'cached_input_tokens': 0, 'uncached_input_tokens': 0, 'output_tokens': 0,
            'cost': 0.0}
