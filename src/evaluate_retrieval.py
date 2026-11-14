"""Compare retrieval configurations on one split (default dev). No LLM, no gold in the query.

Hit rule (Day 7): a chunk is a hit for a gold piece when source_id and page match AND the evidence is an exact
substring of the chunk text. evidence_rule "any": any gold alternative; "all": every piece must be covered
(Hit@1: all pieces in the rank-1 chunk; Hit@3 / context: all pieces across the top-3 / the packed context).
Context = results packed in rank order into a character budget with starter/baseline.pack_context
(header "[id | source | page N]" counted; chunks that do not fit are skipped).
Unanswerable questions are excluded from denominators; their top scores are kept for abstention analysis.

    PYTHONUTF8=1 .venv/Scripts/python.exe src/evaluate_retrieval.py --split dev
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter"))
sys.path.insert(0, str(ROOT / "src"))
from baseline import pack_context  # noqa: E402
from retrieval import Day6Index  # noqa: E402

BENCH = ROOT / "benchmark"
OUT = ROOT / "starter" / "results" / "retrieval"

# Methods compared in Step 3 (same index, same questions, same hit rule, context top-3).
CONFIGS = {
    "R1_dense":         {"method": "dense",   "use_filter": False, "top_k": 3, "options": {}},
    "R2_dense_filter":  {"method": "dense",   "use_filter": True,  "top_k": 3, "options": {}},
    "R3_lexical":       {"method": "lexical", "use_filter": False, "top_k": 3, "options": {}},
    "R4_hybrid":        {"method": "hybrid",  "use_filter": False, "top_k": 3, "options": {"dense_weight": 0.5}},
}
BUDGETS = [800, 2400]


def piece_hit(chunk: dict, piece: dict) -> bool:
    return (chunk["source_id"] == piece["source_id"] and chunk["page"] == piece["page"]
            and piece["evidence"] in chunk["text"])


def covered(chunks: list[dict], q: dict) -> bool:
    if q.get("evidence_rule", "any") == "all":
        return all(any(piece_hit(c, p) for c in chunks) for p in q["gold"])
    return any(piece_hit(c, p) for c in chunks for p in q["gold"])


def run(index: Day6Index, name: str, cfg: dict, questions: list[dict], unanswerable: list[dict]) -> dict:
    traces = []
    for q in questions + unanswerable:
        filters = q.get("filter") if cfg["use_filter"] else None
        t0 = time.perf_counter()
        results = index.search(cfg["method"], q["question"], cfg["top_k"], filters, **cfg["options"])
        ms = (time.perf_counter() - t0) * 1000
        trace = {"query_id": q["id"], "split": q["split"], "answerable": q.get("answerable", True),
                 "question": q["question"], "query_used": q["question"], "config": name, **cfg,
                 "filter_applied": filters, "elapsed_ms": round(ms, 1),
                 "results": [{k: r[k] for k in ("id", "rank", "score", "page", "source_id", "metadata", "text")}
                             for r in results]}
        if q.get("answerable", True):
            trace["evidence_rule"] = q.get("evidence_rule", "any")
            trace["hit1"] = covered(results[:1], q)
            trace["hit3"] = covered(results[:3], q)
            trace["hit_per_rank"] = [any(piece_hit(r, p) for p in q["gold"]) for r in results]
            for budget in BUDGETS:
                context, ids = pack_context(results, budget=budget)
                in_context = [r for r in results if r["id"] in ids]
                trace[f"context_hit_{budget}"] = covered(in_context, q)
                trace[f"context_chars_{budget}"] = len(context)
                trace[f"context_chunks_{budget}"] = len(ids)
        else:
            trace["top_score"] = results[0]["score"] if results else None
        traces.append(trace)
    ans = [t for t in traces if t["answerable"]]
    n = len(ans)
    summary = {"config": name, **cfg, "n_answerable": n,
               "hit1": sum(t["hit1"] for t in ans), "hit3": sum(t["hit3"] for t in ans),
               "median_ms": round(statistics.median(t["elapsed_ms"] for t in traces), 1),
               "unanswerable_top_scores": {t["query_id"]: t["top_score"] for t in traces if not t["answerable"]},
               "answerable_top1_scores_median": round(statistics.median(t["results"][0]["score"] for t in ans), 4)}
    for budget in BUDGETS:
        summary[f"context_hit_{budget}"] = sum(t[f"context_hit_{budget}"] for t in ans)
        summary[f"mean_context_chunks_{budget}"] = round(statistics.mean(t[f"context_chunks_{budget}"] for t in ans), 2)
    summary["filter_questions"] = sum(1 for t in ans if (questions_by_id[t["query_id"]].get("filter")))
    return {"summary": summary, "traces": traces}


questions_by_id: dict[str, dict] = {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--configs", nargs="*", default=list(CONFIGS))
    args = parser.parse_args()
    if args.split == "test":
        print("WARNING: test split - only run after the configuration is frozen on dev.")
    answerable = [q for q in json.loads((BENCH / "answerable.json").read_text(encoding="utf-8")) if q["split"] == args.split]
    unanswerable = [q for q in json.loads((BENCH / "unanswerable.json").read_text(encoding="utf-8")) if q["split"] == args.split]
    questions_by_id.update({q["id"]: q for q in answerable + unanswerable})
    index = Day6Index()
    OUT.mkdir(parents=True, exist_ok=True)
    summaries = []
    for name in args.configs:
        result = run(index, name, CONFIGS[name], answerable, unanswerable)
        (OUT / f"{args.split}_{name}_traces.json").write_text(json.dumps(result["traces"], ensure_ascii=False, indent=1), encoding="utf-8")
        summaries.append(result["summary"])
        s = result["summary"]
        print(f"{name:17} Hit@1 {s['hit1']}/{s['n_answerable']}  Hit@3 {s['hit3']}/{s['n_answerable']}  "
              f"ctx@800 {s['context_hit_800']}/{s['n_answerable']} ({s['mean_context_chunks_800']} chunks)  "
              f"ctx@2400 {s['context_hit_2400']}/{s['n_answerable']} ({s['mean_context_chunks_2400']} chunks)  "
              f"{s['median_ms']} ms")
    report = {"split": args.split, "index": f"Day 6 pgvector, strategy {index.strategy} ({index.size} chunks)",
              "embedding": "openai text-embedding-3-small (1536d), queries cached in Day 6 embedding_cache",
              "new_embedding_tokens": index.embed_tokens, "embedding_calls": index.embed_calls,
              "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "summaries": summaries}
    (OUT / f"{args.split}_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"new embedding tokens: {index.embed_tokens} ({index.embed_calls} calls)")


if __name__ == "__main__":
    main()
