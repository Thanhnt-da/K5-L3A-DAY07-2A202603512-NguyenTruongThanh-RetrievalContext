"""Run an agent configuration over a benchmark split and save traces + automatic metrics.

Automatic (computed here): status counts, tool use, searches per question, Context Evidence Rate
(gold evidence inside the FINAL context sent to the model, evidence_rule any/all), tokens, cost, time, errors.
Manual (done later by the author, in an Excel sheet): answer grade 0/1/2, citation support, abstention correctness.

    PYTHONUTF8=1 .venv/Scripts/python.exe src/run_agent.py --config A0_baseline --split dev
    PYTHONUTF8=1 .venv/Scripts/python.exe src/run_agent.py --config A0_baseline --split dev --only q01 u01
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent import Agent, AgentConfig  # noqa: E402
from retrieval import Day6Index  # noqa: E402

BENCH = ROOT / "benchmark"
OUT = ROOT / "starter" / "results" / "agent"

CONFIGS = {
    # Baseline = starter defaults: dense, top-3 per search, 800-char context, up to 4 searches.
    "A0_baseline": AgentConfig(name="A0_baseline", method="dense", top_k=3, budget=800, max_searches=4,
                               notes="starter defaults on the Day 6 dense index"),
    # Improvement configs; hypotheses in docs/experiments.md (written before the runs).
    "A1_budget2400": AgentConfig(name="A1_budget2400", method="dense", top_k=3, budget=2400, max_searches=4,
                                 notes="A0 + context budget 800 -> 2400 chars"),
    "A2_filter": AgentConfig(name="A2_filter", method="dense", top_k=3, budget=2400, max_searches=4,
                             use_filter=True, notes="A1 + user-given chapter filter"),
    "A3_hybrid": AgentConfig(name="A3_hybrid", method="hybrid", top_k=3, budget=2400, max_searches=4,
                             use_filter=True, dense_weight=0.75, notes="A2 with hybrid RRF (w=0.75, Day 6 value)"),
    "A4_diverse_queries": AgentConfig(name="A4_diverse_queries", method="dense", top_k=3, budget=2400,
                                      max_searches=4, use_filter=True, extra={"diverse_queries": True},
                                      notes="A2 + follow-up queries must use different key terms"),
    # Added after reading dev failures of A0-A4 (docs/experiments.md, written before this run).
    "A5_strict_cite": AgentConfig(name="A5_strict_cite", method="dense", top_k=3, budget=2400, max_searches=4,
                                  use_filter=True, extra={"strict": True},
                                  notes="A2 + strict abstention rule + mandatory inline citation format"),
    "A6_self_check": AgentConfig(name="A6_self_check", method="dense", top_k=3, budget=2400, max_searches=4,
                                 use_filter=True, extra={"strict": True, "self_check": True},
                                 notes="A5 + required context_has_exact_item flag; false -> abstention by code"),
}


def load_questions(split: str) -> list[dict]:
    ans = [q for q in json.loads((BENCH / "answerable.json").read_text(encoding="utf-8")) if q["split"] == split]
    una = [q for q in json.loads((BENCH / "unanswerable.json").read_text(encoding="utf-8")) if q["split"] == split]
    return ans + una


def chunk_text_by_id(index: Day6Index, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = index._rows("SELECT chunk_id, document_id, page, content FROM chunks WHERE strategy = %(s)s "
                       "AND chunk_id = ANY(%(ids)s)", {"s": index.strategy, "ids": ids})
    return {r["chunk_id"]: r for r in rows}


def evidence_in_context(q: dict, chunks: dict[str, dict]) -> bool:
    def piece(p):
        return any(c["document_id"] == p["source_id"] and c["page"] == p["page"] and p["evidence"] in c["content"]
                   for c in chunks.values())
    pieces = [piece(p) for p in q["gold"]]
    return all(pieces) if q.get("evidence_rule", "any") == "all" else any(pieces)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, choices=list(CONFIGS))
    parser.add_argument("--split", required=True, choices=["dev", "test"])
    parser.add_argument("--only", nargs="*", help="run only these question ids (smoke test)")
    args = parser.parse_args()
    cfg = CONFIGS[args.config]
    questions = load_questions(args.split)
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]
    index = Day6Index()
    agent = Agent(cfg, index)
    rows = []
    for q in questions:
        try:
            result = agent.run(q["question"], filters=q.get("filter"))   # no gold passed
        except Exception as exc:  # recorded, never replaced by a fake answer
            result = {"status": "error", "answer": None, "citations": [], "events": [],
                      "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=3)}
        row = {"query_id": q["id"], "split": q["split"], "answerable": q.get("answerable", True),
               "question": q["question"], "filter_given": q.get("filter"), **result}
        if row["answerable"] and result["status"] != "error":
            ctx = chunk_text_by_id(index, result["final_context_ids"])
            row["context_evidence"] = evidence_in_context(q, ctx)
            row["evidence_rule"] = q.get("evidence_rule", "any")
        rows.append(row)
        print(f"{q['id']:4} {row['status']:9} searches={result.get('searches', '-')} "
              f"ctx_ev={row.get('context_evidence', '-')} cites={len(result.get('citations', []))} "
              f"{(result.get('answer') or result.get('error') or '')[:110]!r}")

    ok = [r for r in rows if r["status"] != "error"]
    ans = [r for r in ok if r["answerable"]]
    una = [r for r in ok if not r["answerable"]]
    summary = {
        "config": cfg.name, "split": args.split, "questions": len(rows), "errors": len(rows) - len(ok),
        "status": dict(Counter(r["status"] for r in rows)),
        "tool_use": f"{sum(r['searches'] > 0 for r in ok)}/{len(ok)}",
        "searches_distribution": dict(sorted(Counter(r["searches"] for r in ok).items())),
        "context_evidence_rate": f"{sum(r['context_evidence'] for r in ans)}/{len(ans)}",
        "answered_answerable": f"{sum(r['status'] == 'answered' for r in ans)}/{len(ans)}",
        "abstained_unanswerable": f"{sum(r['status'] == 'abstain' for r in una)}/{len(una)}",
        "false_abstention": f"{sum(r['status'] == 'abstain' for r in ans)}/{len(ans)}",
        "invalid_citation_events": sum(any(e['event'] == 'invalid_or_missing_citations' for e in r['events']) for r in ok),
        "input_tokens": sum(r["input_tokens"] for r in ok), "output_tokens": sum(r["output_tokens"] for r in ok),
        "llm_cost_usd": round(sum(r["llm_cost_usd"] or 0 for r in ok), 5),
        "median_elapsed_s": statistics.median(r["elapsed_s"] for r in ok) if ok else None,
        "mean_context_chars": round(statistics.mean(r["final_context_chars"] for r in ok), 1) if ok else None,
        "new_embedding_tokens": index.embed_tokens, "config_detail": cfg.__dict__,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "subset": args.only or "all",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    tag = f"{args.split}_{cfg.name}" + ("_smoke" if args.only else "")
    (OUT / f"{tag}_traces.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"{tag}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "config_detail"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
