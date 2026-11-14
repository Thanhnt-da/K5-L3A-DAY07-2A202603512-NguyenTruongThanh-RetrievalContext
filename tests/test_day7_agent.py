"""Offline tests for src/agent.py and the evidence rules in src/evaluate_retrieval.py.

A scripted fake model and a fake retriever replace OpenAI and pgvector, so these tests check the code paths only
(citation checks, abstention, limits, context budget, filters) - not answer quality. No network, no database.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "starter"))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")  # the client is replaced before any call

from agent import Agent, AgentConfig, pack_context  # noqa: E402
from evaluate_retrieval import covered  # noqa: E402

C1 = {"id": "doc:p0001:para:000", "text": "Relative poverty is below half the median income.", "source_id": "doc",
      "source": "book.pdf", "page": 1, "rank": 1, "score": 0.9, "metadata": {"chapter": 9}}
C2 = {"id": "doc:p0002:para:000", "text": "Deindustrialization follows capital flight.", "source_id": "doc",
      "source": "book.pdf", "page": 2, "rank": 2, "score": 0.8, "metadata": {"chapter": 10}}


class FakeModel:
    """Returns scripted tool calls in order; records the tools offered on each call."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.offered_tools = []
        self.tool_schemas = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.offered_tools.append([t["function"]["name"] for t in kwargs["tools"]])
        self.tool_schemas.append({t["function"]["name"]: t["function"] for t in kwargs["tools"]})
        name, args = self.actions.pop(0)
        call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
                               choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


class FakeIndex:
    def __init__(self, results, error=None):
        self.results, self.error, self.calls = results, error, []

    def search(self, method, query, top_k, filters, **options):
        self.calls.append({"method": method, "query": query, "top_k": top_k, "filters": filters, **options})
        if self.error:
            raise self.error
        return self.results[:top_k]


def make_agent(actions, results=(C1,), **cfg):
    config = AgentConfig(name="test", **{"budget": 2400, **cfg})
    agent = Agent(config, index=FakeIndex(list(results)))
    agent.client = FakeModel(actions)
    return agent


def answer(text, cites, **extra):
    return ("answer", {"answer": text, "citations": cites, **extra})


class AgentLoopTests(unittest.TestCase):
    def test_answer_with_inline_citation_from_context_is_accepted(self):
        a = make_agent([("search", {"query": "relative poverty"}), answer(f"Below half [{C1['id']}].", [C1["id"]])])
        r = a.run("What is relative poverty?")
        self.assertEqual(r["status"], "answered")
        self.assertEqual(r["citations"], [C1["id"]])
        self.assertEqual(r["final_context_ids"], [C1["id"]])
        self.assertEqual(r["searches"], 1)
        self.assertEqual(r["model_calls"], 2)

    def test_citation_not_in_context_becomes_abstention(self):
        a = make_agent([("search", {"query": "q"}), answer(f"X [{C2['id']}].", [C2["id"]])])
        r = a.run("q")
        self.assertEqual(r["status"], "abstain")
        self.assertEqual(r["citations"], [])
        self.assertEqual(r["events"][-1]["event"], "invalid_or_missing_citations")

    def test_citation_missing_inline_becomes_abstention(self):
        a = make_agent([("search", {"query": "q"}), answer("Below half the median.", [C1["id"]])])
        self.assertEqual(a.run("q")["status"], "abstain")

    def test_answer_without_citations_becomes_abstention(self):
        a = make_agent([("search", {"query": "q"}), answer("Below half the median.", [])])
        self.assertEqual(a.run("q")["status"], "abstain")

    def test_abstain_tool_records_reason(self):
        a = make_agent([("search", {"query": "q"}), ("abstain", {"reason": "names not given"})])
        r = a.run("q")
        self.assertEqual(r["status"], "abstain")
        self.assertEqual(r["events"][-1], {"event": "abstain", "reason": "names not given"})

    def test_self_check_false_becomes_abstention(self):
        a = make_agent([("search", {"query": "q"}),
                        answer(f"Not stated, however [{C1['id']}].", [C1["id"]], context_has_exact_item=False)],
                       extra={"strict": True, "self_check": True})
        r = a.run("q")
        self.assertEqual(r["status"], "abstain")
        self.assertEqual(r["events"][-1]["event"], "self_reported_missing")

    def test_self_check_flag_is_required_only_when_enabled(self):
        acts = [("search", {"query": "q"}), answer(f"Y [{C1['id']}].", [C1["id"]], context_has_exact_item=True)]
        checked, plain = make_agent(list(acts), extra={"self_check": True}), make_agent(list(acts))
        self.assertEqual(checked.run("q")["status"], "answered")
        plain.run("q")
        required = lambda a: a.client.tool_schemas[0]["answer"]["parameters"]["required"]
        self.assertIn("context_has_exact_item", required(checked))
        self.assertNotIn("context_has_exact_item", required(plain))
        self.assertNotIn("context_has_exact_item", json.dumps(__import__("agent").TOOLS))  # base schema untouched

    def test_search_limit_removes_search_tool_and_stops(self):
        a = make_agent([("search", {"query": "a"}), ("search", {"query": "b"}), ("abstain", {"reason": "none"})],
                       max_searches=2)
        r = a.run("q")
        self.assertEqual(r["searches"], 2)
        self.assertNotIn("search", a.client.offered_tools[-1])
        self.assertEqual(r["status"], "abstain")

    def test_search_call_beyond_limit_is_not_executed(self):
        a = make_agent([("search", {"query": "a"}), ("search", {"query": "b"})], max_searches=1)
        r = a.run("q")
        self.assertEqual(len(a.index.calls), 1)
        self.assertEqual(r["status"], "abstain")
        self.assertEqual(r["events"][-1]["event"], "search_limit")

    def test_filter_passed_only_when_enabled(self):
        acts = [("search", {"query": "q"}), ("abstain", {"reason": "-"})]
        on, off = make_agent(list(acts), use_filter=True), make_agent(list(acts), use_filter=False)
        on.run("q", filters={"chapter": 10})
        off.run("q", filters={"chapter": 10})
        self.assertEqual(on.index.calls[0]["filters"], {"chapter": 10})
        self.assertIsNone(off.index.calls[0]["filters"])

    def test_retriever_error_propagates(self):
        a = make_agent([("search", {"query": "q"})])
        a.index = FakeIndex([], error=RuntimeError("database down"))
        with self.assertRaises(RuntimeError):
            a.run("q")

    def test_empty_query_is_rejected(self):
        with self.assertRaises(ValueError):
            make_agent([("search", {"query": "  "})]).run("q")


class ContextAndEvidenceTests(unittest.TestCase):
    def test_pack_context_skips_chunks_that_do_not_fit_and_duplicates(self):
        long = {**C2, "id": "long", "text": "x" * 900}
        context, ids = pack_context([C1, long, C1, C2], budget=300)
        self.assertEqual(ids, [C1["id"], C2["id"]])
        self.assertLessEqual(len(context), 300)

    def test_budget_limits_what_the_model_sees(self):
        long = {**C1, "id": "long", "text": "y" * 900}
        a = make_agent([("search", {"query": "q"}), answer("Y [long].", ["long"])], results=(long,), budget=800)
        r = a.run("q")
        self.assertEqual(r["final_context_ids"], [])
        self.assertEqual(r["status"], "abstain")

    def test_evidence_rule_all_needs_every_piece(self):
        q = {"evidence_rule": "all", "gold": [{"source_id": "doc", "page": 1, "evidence": "Relative poverty"},
                                              {"source_id": "doc", "page": 2, "evidence": "capital flight"}]}
        self.assertFalse(covered([C1], q))
        self.assertTrue(covered([C1, C2], q))

    def test_evidence_rule_any_accepts_one_alternative_on_the_right_page(self):
        q = {"gold": [{"source_id": "doc", "page": 1, "evidence": "Relative poverty"},
                      {"source_id": "doc", "page": 9, "evidence": "capital flight"}]}
        self.assertTrue(covered([C1], q))
        self.assertFalse(covered([C2], q))  # right text, wrong page


if __name__ == "__main__":
    unittest.main()
