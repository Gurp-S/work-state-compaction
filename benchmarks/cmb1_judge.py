"""LLM judging for chat-memory-benchmark 1.0 review packets.

Usage:
    python benchmarks/cmb1_judge.py --packets packets.jsonl --out reviews.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "experiments" / "cmb"
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "src"))

from cmb_llm import ThrottledChat  # noqa: E402
from parallel_eval import parallel_map  # noqa: E402

FLAGS = ("错认", "错否", "越界", "编造日期", "不当私事披露")
LISTS = ("违反禁止", "未知当事实", "无关旧事")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()]


def parse_review(text: str) -> dict:
    candidates = []
    depth = 0
    start = None
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    value = json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and "required" in value:
                    candidates.append(value)
    if not candidates:
        raise ValueError(f"no review object in output: {text[:200]}")
    return candidates[-1]


def check(review: dict, packet: dict) -> dict:
    rubric = packet["rubric"]
    required = review.get("required")
    if (not isinstance(required, list) or len(required) != len(rubric.get("required", []))
            or any(type(item) is not bool for item in required)):
        raise ValueError("required mismatch")
    for key in FLAGS:
        if type(review.get(key)) is not bool:
            raise ValueError(f"{key} not bool")
    for key in LISTS:
        value = review.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{key} not list of strings")
    if not isinstance(review.get("reason"), str) or not review["reason"].strip():
        raise ValueError("reason missing")
    return {"id": packet["id"], "answer_sha256": packet["answer_sha256"],
            "rubric_sha256": packet["rubric_sha256"], "required": required,
            **{key: review[key] for key in (*FLAGS, *LISTS)},
            "reason": review["reason"].strip()[:400]}


STRIP = str.maketrans("", "", " \t\r\n，。！？；：、“”‘’（）()【】[]…—-·.,!?;:\"'")


def _norm(text: str) -> str:
    return text.translate(STRIP)


def fallback(packet: dict) -> dict:
    """Keep one failed judge call from voiding the whole exam; mark it as lexical."""
    answer = _norm(packet["answer"])
    rubric = packet["rubric"]
    required = [all(_norm(clause) in answer for clause in item.split("；") if _norm(clause))
                for item in rubric.get("required", [])]
    forbidden = [item for item in rubric.get("forbidden", []) if _norm(item) in answer]
    unknown = [item for item in rubric.get("unknown", []) if _norm(item) in answer]
    return {"id": packet["id"], "answer_sha256": packet["answer_sha256"],
            "rubric_sha256": packet["rubric_sha256"], "required": required,
            "错认": False, "错否": False, "越界": False, "编造日期": False,
            "不当私事披露": False, "违反禁止": forbidden, "未知当事实": unknown,
            "无关旧事": [], "reason": "lexical_fallback"}


def judge(chat: Chat, prompt: str, packet: dict) -> dict:
    user = json.dumps(packet, ensure_ascii=False)
    last = None
    for _ in range(4):
        try:
            text = chat.ask(prompt, user, max_tokens=900, purpose="format")
            return check(parse_review(text), packet)
        except (ValueError, json.JSONDecodeError) as error:
            last = error
            time.sleep(1)
    raise RuntimeError(f"{packet['id']}: {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, default=REPO / "grading" / "judge-prompt.md")
    args = parser.parse_args()
    prompt = args.prompt.read_text(encoding="utf-8")
    packets = rows(args.packets)
    chat = ThrottledChat()
    started = time.time()

    def work(packet):
        try:
            review = judge(chat, prompt, packet)
        except Exception as error:  # a gateway failure must not void the whole exam
            review = fallback(packet)
            review["reason"] += f" ({type(error).__name__})"
        print(f"{packet['id']} {'required_all' if all(review['required']) else 'required_miss'}",
              flush=True)
        return review

    reviews = parallel_map(work, packets)
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        for review in reviews:
            handle.write(json.dumps(review, ensure_ascii=False) + "\n")
    print(json.dumps({"reviews": len(reviews), "calls": chat.calls,
                      "seconds": round(time.time() - started, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
