"""Coding-agent gaps: layered scopes, commit anchors, observation vs state, redaction."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import (CSM, CSMError, CsmStore, Event, MemoryCandidate, MemoryQuery,
                     branch_scope, chain, repo_scope)
from wsc.csm.index import terms

REPO = "acme/api"
MAIN = branch_scope(REPO, "main")
REPO_SCOPE = repo_scope(REPO)


def event(event_id, commit, observed_at, text="observed"):
    return Event(event_id, "git", {"text": text}, source_ref=commit,
                 observed_at=observed_at, metadata={"commit": commit})


class CodingFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db = self.root / "memory.db"
        self.core = CSM(CsmStore(self.db, namespace="repo:acme/api"))
        self.core.ingest([
            event("c1", "a" * 40, "2026-01-01T00:00:00Z"),
            event("c2", "b" * 40, "2026-02-01T00:00:00Z"),
        ])

    def remember(self, **overrides):
        data = {"entity": REPO, "slot": "runtime", "value": "python3.10",
                "scope": REPO_SCOPE, "source_ids": ("c1",)}
        data.update(overrides)
        return self.core.remember([MemoryCandidate(**data)])[0]

    def query(self, **overrides):
        data = {"entity": REPO, "slot": "runtime", "with_evidence": False}
        data.update(overrides)
        return self.core.query(MemoryQuery(**data))


class ScopeTests(CodingFixture):
    def test_chain_is_specific_to_general(self):
        self.assertEqual((MAIN, REPO_SCOPE, "entity"), chain(MAIN))

    def test_branch_state_overrides_repository_state(self):
        self.remember()
        self.remember(value="python3.12", scope=MAIN, source_ids=("c2",))
        widened = self.query(scope=MAIN, scope_chain=True)
        self.assertEqual(1, len(widened["results"]))
        self.assertEqual("python3.12", widened["results"][0]["value"])
        self.assertEqual(MAIN, widened["results"][0]["origin_scope"])

        repository = self.query(scope=REPO_SCOPE, scope_chain=True)
        self.assertEqual("python3.10", repository["results"][0]["value"])

    def test_branch_exact_does_not_see_repository(self):
        self.remember()
        self.assertEqual([], self.query(scope=MAIN)["results"])

    def test_search_respects_scope(self):
        self.remember()
        self.assertEqual(1, len(self.core.search("python3.10", scope=REPO_SCOPE)["results"]))
        self.assertEqual(0, len(self.core.search("python3.10", scope=MAIN)["results"]))

    def test_search_prefers_branch_state_over_repository(self):
        self.remember(value="python3 repo")
        self.remember(value="python3 branch", scope=MAIN, source_ids=("c2",))
        widened = self.core.search("python3", scope=MAIN, scope_chain=True)["results"]
        self.assertEqual(1, len(widened))
        self.assertEqual("python3 branch", widened[0]["value"])


class CommitTests(CodingFixture):
    def test_commit_anchor_selects_the_past_revision(self):
        self.remember()
        self.remember(value="python3.12", source_ids=("c2",))
        old = self.query(at_commit="a" * 40)
        self.assertEqual("python3.10", old["results"][0]["value"])
        self.assertEqual("HISTORICAL", old["results"][0]["classification"])
        self.assertEqual("a" * 40, old["results"][0]["commit"])
        new = self.query(at_commit="b" * 40)
        self.assertEqual("python3.12", new["results"][0]["value"])
        self.assertEqual("CURRENT_CONFIRMED", new["results"][0]["classification"])

    def test_unknown_commit_is_refused(self):
        with self.assertRaises(CSMError):
            self.query(at_commit="f" * 40)

    def test_search_can_anchor_on_a_commit(self):
        self.remember()
        self.remember(value="python3.12", source_ids=("c2",))
        old = self.core.search("python3.12", at_commit="a" * 40)["results"]
        self.assertEqual("python3.10", old[0]["value"])
        new = self.core.search("python3.12", at_commit="b" * 40)["results"]
        self.assertEqual(1, len(new))
        self.assertEqual("b" * 40, new[0]["commit"])

    def test_commit_and_instant_are_mutually_exclusive(self):
        with self.assertRaises(CSMError):
            self.query(at_commit="a" * 40, valid_at="2026-01-01T00:00:00Z")


class KindTests(CodingFixture):
    def test_decision_appends_and_state_overwrites(self):
        self.remember(slot="decision", value="use postgres")
        self.remember(slot="decision", value="use sqlite", source_ids=("c2",))
        decisions = self.query(slot="decision", scope=REPO_SCOPE)
        self.assertEqual(2, len(decisions["results"]))
        self.assertEqual({"use postgres", "use sqlite"},
                         {item["value"] for item in decisions["results"]})

        self.remember()
        self.remember(value="python3.12", source_ids=("c2",))
        state = self.query(scope=REPO_SCOPE)
        self.assertEqual(1, len(state["results"]))
        self.assertEqual("python3.12", state["results"][0]["value"])

    def test_duplicate_observation_creates_no_revision(self):
        first = self.remember()
        again = self.remember()
        self.assertFalse(again["changed"])
        self.assertEqual(first["revision"], again["revision"])


class NormalizationTests(unittest.TestCase):
    def test_issue_reference_is_stripped(self):
        tokens = terms("Fix #123 parser crash")
        self.assertNotIn("123", tokens)
        self.assertIn("parser", tokens)
        self.assertIn("crash", tokens)

    def test_template_verbs_are_dropped(self):
        tokens = terms("Update docs and add tests for parser")
        self.assertNotIn("update", tokens)
        # only "update" is a measured template verb; "add" and "docs" stay searchable
        for word in ("add", "docs", "parser", "tests"):
            self.assertIn(word, tokens)

    def test_plain_number_is_kept(self):
        self.assertIn("24", terms("24岁"))


class RedactionTests(unittest.TestCase):
    def test_secrets_never_reach_the_event_log(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "memory.db"
        core = CSM(CsmStore(path, namespace="repo:secret"))
        result = core.ingest([Event(
            "s1", "file",
            {"text": "password=hunter2secret\nGITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123"},
            observed_at="2026-01-01T00:00:00Z", metadata={"token": "keep-out"})])
        self.assertGreaterEqual(result["redacted"], 2)
        with closing(sqlite3.connect(path)) as connection:
            payload, metadata = connection.execute(
                "SELECT data, metadata FROM events WHERE id = 's1'").fetchone()
        self.assertNotIn("hunter2secret", payload)
        self.assertNotIn("ghp_", payload)
        self.assertNotIn("keep-out", metadata)
        self.assertIn("[REDACTED", payload)

    def test_projection_table_is_not_created_or_written(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "memory.db"
        core = CSM(CsmStore(path, namespace="repo:acme/api"))
        core.ingest([event("c1", "a" * 40, "2026-01-01T00:00:00Z")])
        core.remember([MemoryCandidate(entity=REPO, slot="runtime", value="python3.10",
                                       scope=REPO_SCOPE, source_ids=("c1",))])
        with closing(sqlite3.connect(path)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn("projection", tables)

    def test_status_counts_commits(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        core = CSM(CsmStore(Path(directory.name) / "memory.db", namespace="repo:acme/api"))
        core.ingest([event("c1", "a" * 40, "2026-01-01T00:00:00Z")])
        self.assertEqual(1, core.status()["commits"])


class SymbolIndexTests(CodingFixture):
    def setUp(self):
        super().setUp()
        from wsc.csm import retrieval
        self.retrieval = retrieval
        previous = retrieval.SYMBOL_WEIGHT
        self.addCleanup(setattr, retrieval, "SYMBOL_WEIGHT", previous)

    def test_adopted_retrieval_defaults(self):
        self.assertEqual(1.0, self.retrieval.SYMBOL_WEIGHT)
        self.assertEqual(0.0, self.retrieval.SYMBOL_CAP)
        self.assertEqual(0, self.retrieval.SYMBOL_GATE_K)
        self.assertEqual(0.0, self.retrieval.SYMBOL_GATE_SCORE)

    def search(self, text, **overrides):
        data = {"limit": 10, "with_evidence": False}
        data.update(overrides)
        return self.core.search(text, **data)["results"]

    def test_symbol_hit_when_subject_does_not_mention_it(self):
        self.remember(value="tidy docs", symbols=("timeout",), scope=REPO_SCOPE)
        self.retrieval.SYMBOL_WEIGHT = 0.0
        self.assertEqual([], self.search("timeout"))
        self.retrieval.SYMBOL_WEIGHT = 1.0
        self.assertEqual("tidy docs", self.search("timeout")[0]["value"])

    def test_zero_weight_is_the_old_behaviour(self):
        self.remember(value="tidy docs", symbols=("timeout",), scope=REPO_SCOPE)
        self.retrieval.SYMBOL_WEIGHT = 0.0
        self.assertEqual([], self.search("timeout"))
        self.assertEqual(1, len(self.search("docs")))

    def test_symbols_stay_out_of_identity(self):
        self.remember(value="python3.10", symbols=("parser",), scope=REPO_SCOPE)
        second = self.remember(value="python3.12", symbols=("lexer",), scope=REPO_SCOPE,
                               source_ids=("c2",))
        self.assertEqual("update", second["operation"])
        self.assertEqual(2, second["revision"])
        with closing(sqlite3.connect(self.db)) as connection:
            stored = {row[0] for row in connection.execute(
                "SELECT symbol FROM memory_symbols WHERE memory_id = ?",
                (second["memory_id"],))}
        self.assertEqual({"parser", "lexer"}, stored)

    def test_rebuild_restores_symbol_index(self):
        self.remember(value="tidy docs", symbols=("timeout",), scope=REPO_SCOPE)
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("DELETE FROM symbol_index")
            connection.commit()
            self.assertEqual(0, connection.execute(
                "SELECT COUNT(*) FROM symbol_index").fetchone()[0])
        self.core.rebuild()
        self.retrieval.SYMBOL_WEIGHT = 1.0
        self.assertEqual("tidy docs", self.search("timeout")[0]["value"])

    def test_symbol_reaches_historical_revision(self):
        self.remember(value="tidy docs", symbols=("timeout",), scope=REPO_SCOPE)
        self.remember(value="rewritten docs", symbols=("timeout",), scope=REPO_SCOPE,
                      source_ids=("c2",))
        self.retrieval.SYMBOL_WEIGHT = 1.0
        old = self.search("timeout", window=(None, "2026-01-15T00:00:00Z"))
        self.assertEqual("tidy docs", old[0]["value"])
        current = self.search("timeout")
        self.assertEqual("rewritten docs", current[0]["value"])

    def test_symbol_list_is_bounded(self):
        with self.assertRaises(CSMError):
            self.remember(value="x", symbols=tuple(f"token{index:03d}" for index in range(65)))

    def test_anchor_reaches_symbol_terms(self):
        self.remember(value="tidy docs", symbols=("timeout",), scope=REPO_SCOPE)
        self.retrieval.SYMBOL_WEIGHT = 0.0
        self.assertEqual([], self.search("timeout"))
        found = self.core.search("docs", limit=10, with_evidence=False,
                                 anchor="_handle_timeout(request)")["results"]
        self.assertEqual(["tidy docs"], [row["value"] for row in found])
        self.retrieval.SYMBOL_WEIGHT = 1.0
        found = self.core.search("docs", limit=10, with_evidence=False,
                                 anchor="_handle_timeout(request)")["results"]
        self.assertTrue(any(row["value"] == "tidy docs" for row in found))
        self.assertEqual(self.search("docs"),
                         self.core.search("docs", limit=10, with_evidence=False,
                                          anchor=None)["results"])

    def test_query_terms_split_identifiers(self):
        from wsc.csm import symbols
        self.assertEqual("timeout", symbols.query_terms("_handle_timeout(timeout)")[0])
        self.assertIn("handle", symbols.query_terms("_handle_timeout(timeout)"))
        self.assertEqual([], symbols.query_terms("self value None"))


if __name__ == "__main__":
    unittest.main()
