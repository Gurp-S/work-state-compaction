"""Deterministic secret scrubbing for ingested evidence.

Evidence is stored verbatim so an answer can be grounded in what was actually said; the one
exception is credentials, which must never reach the log. Substitution is pattern-based and
idempotent, so re-ingesting the same event still hashes to the same digest.
"""
from __future__ import annotations

import re

_PATTERNS = (
    ("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL)),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("api_token", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("url_credential", re.compile(r"(://)[^/\s:@]{1,64}:[^@\s/]{3,64}@")),
    ("credential", re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
        r"client[_-]?secret|private[_-]?key)\b(\s*[:=]\s*)([\"']?)[^\s\"',;]{8,}\3")),
)

_SECRET_KEY = re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|"
                         r"access[_-]?key|client[_-]?secret|private[_-]?key)")


def text(value: str) -> tuple[str, int]:
    out, count = value, 0
    for label, pattern in _PATTERNS:
        if label == "url_credential":
            out, hits = pattern.subn(r"\1[REDACTED:" + label + "]@", out)
        elif label == "credential":
            out, hits = pattern.subn(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}"
                                              f"[REDACTED:{label}]{m.group(3)}", out)
        else:
            out, hits = pattern.subn(f"[REDACTED:{label}]", out)
        count += hits
    return out, count


def payload(value):
    """Scrub strings recursively; sensitive metadata keys lose their value entirely."""
    if isinstance(value, str):
        return text(value)
    if isinstance(value, dict):
        out, count = {}, 0
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key):
                out[key] = "[REDACTED:credential]"
                count += 1
                continue
            cleaned, hits = payload(item)
            out[key] = cleaned
            count += hits
        return out, count
    if isinstance(value, (list, tuple)):
        out, count = [], 0
        for item in value:
            cleaned, hits = payload(item)
            out.append(cleaned)
            count += hits
        return out, count
    return value, 0


__all__ = ["text", "payload"]
