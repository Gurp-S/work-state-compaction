"""Denoise rules keep identity and control rows, and report what they removed."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wsc.denoise import RULES, apply_rules, summarize
from wsc.denoise.registry import row_size
from wsc.contracts import WSCError


def row(seq, kind, payload, text=None, role=None, call_id=None, control=False):
    return {"seq": seq, "id": f"s{seq}", "kind": kind, "payload": payload, "text": text,
            "role": role, "call_id": call_id, "control": control}


class DenoiseTests(unittest.TestCase):
    def test_control_rows_pass_through_every_rule(self):
        rows = [row(1, "message", {"text": "task"}, "task", role="user", control=True),
                row(2, "result", {"output": "x" * 9000}, "x" * 9000, call_id="c1")]
        result, _ = apply_rules(rows, None)
        self.assertEqual(rows[0], result[0])

    def test_identity_fields_are_preserved(self):
        rows = [row(1, "result", {"path": "a.py", "content": "old"}, "old", call_id="c1"),
                row(2, "result", {"path": "a.py", "content": "new"}, "new", call_id="c2")]
        result, _ = apply_rules(rows, ["dedupe_reads"])
        self.assertEqual([(r["id"], r["kind"], r["call_id"]) for r in rows],
                         [(r["id"], r["kind"], r["call_id"]) for r in result])

    def test_dedupe_identical_points_at_the_first_occurrence(self):
        text = "same output " * 40
        rows = [row(1, "result", {"output": text}, text, call_id="c1"),
                row(2, "result", {"output": text}, text, call_id="c2")]
        result, actions = apply_rules(rows, ["dedupe_identical"])
        self.assertEqual(1, len(actions))
        self.assertEqual(rows[0]["id"], actions[0].pointer["same_as"])
        self.assertLess(row_size(result[1]), row_size(rows[1]))

    def test_dedupe_never_grows_a_row(self):
        rows = [row(1, "result", {"output": "a"}, "a", call_id="c1"),
                row(2, "result", {"output": "a"}, "a", call_id="c2")]
        result, actions = apply_rules(rows, ["dedupe_identical"])
        self.assertEqual([], actions)
        self.assertEqual(rows, result)

    def test_dedupe_reads_keeps_the_newest_observation(self):
        old, new = "v1\n" * 40, "v2\n" * 40
        rows = [row(1, "result", {"path": "a.py", "content": old}, old, call_id="c1"),
                row(2, "result", {"path": "a.py", "content": new}, new, call_id="c2")]
        result, actions = apply_rules(rows, ["dedupe_reads"])
        self.assertEqual(rows[1]["id"], result[1]["id"])
        self.assertEqual(new, result[1]["text"])
        self.assertEqual(rows[1]["id"], actions[0].pointer["superseded_by"])

    def test_truncation_keeps_head_and_tail(self):
        text = "H" * 3000 + "M" * 5000 + "T" * 2000
        rows = [row(1, "result", {"output": text}, text, call_id="c1")]
        result, actions = apply_rules(rows, ["truncate_head_tail"])
        trimmed = result[0]["text"]
        self.assertTrue(trimmed.startswith("H" * 100))
        self.assertTrue(trimmed.endswith("T" * 100))
        self.assertIn("chars omitted", trimmed)
        self.assertGreater(actions[0].saved, 0)

    def test_outline_json_is_smaller_and_keeps_a_pointer(self):
        payload = {"items": [{"id": f"i{n}", "body": "x" * 100} for n in range(60)]}
        rows = [row(1, "result", payload, None, call_id="c1")]
        result, actions = apply_rules(rows, ["outline_json"])
        self.assertLess(row_size(result[0]), row_size(rows[0]))
        self.assertEqual("source_read", actions[0].pointer["recover"])

    def test_report_totals_match_actions(self):
        rows = [row(1, "result", {"output": "x" * 9000}, "x" * 9000, call_id="c1")]
        result, actions = apply_rules(rows, ["truncate_head_tail"])
        report = summarize(actions, len(rows), len(result))
        self.assertEqual(actions[0].saved, report["saved_bytes"])
        self.assertEqual(1.0, report["recoverable_ratio"])

    def test_unknown_rule_is_rejected(self):
        with self.assertRaisesRegex(WSCError, "denoise_rule_unknown"):
            apply_rules([], ["nope"])

    def test_every_registered_rule_declares_reversibility(self):
        for name, module in RULES().items():
            self.assertIn(module.REVERSIBLE, {"exact", "pointer", "lossy"}, name)


if __name__ == "__main__":
    unittest.main()
