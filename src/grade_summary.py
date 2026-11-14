"""Read the filled grading workbook -> cases/traces/reviews JSON -> starter/agent_metrics.py, plus context scores.

Never fills a missing label: empty or invalid cells are reported and the script stops.
    PYTHONUTF8=1 .venv/Scripts/python.exe src/grade_summary.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
GRADING = ROOT / "starter" / "results" / "grading"
AGENT = ROOT / "starter" / "results" / "agent"


def as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().upper() in ("TRUE", "FALSE"):
        return v.strip().upper() == "TRUE"
    return None


def rows(wb, name):
    ws = wb[name]
    head = [c.value for c in ws[2]]
    return [dict(zip(head, r)) for r in ws.iter_rows(min_row=3, values_only=True) if r[0]]


def main() -> int:
    wb = load_workbook(GRADING / "grading_test.xlsx")
    answers, cites, contexts = rows(wb, "1_Answers"), rows(wb, "2_Citations"), rows(wb, "3_Context")
    problems = []
    for r in answers:
        if r["answerable"] and r["answer_grade"] not in (0, 1, 2, "0", "1", "2"):
            problems.append(f"{r['row_id']} ({r['config']} {r['qid']}): answer_grade missing/invalid")
        if not r["answerable"] and as_bool(r["abstention_correct"]) is None:
            problems.append(f"{r['row_id']} ({r['config']} {r['qid']}): abstention_correct missing")
    for r in cites:
        if as_bool(r["supports"]) is None:
            problems.append(f"{r['row_id']} ({r['config']} {r['qid']}): citation 'supports' missing")
    for r in contexts:
        if r["context_score"] not in (0, 1, 2, "0", "1", "2"):
            problems.append(f"{r['row_id']} ({r['config']} {r['qid']}): context_score missing/invalid")
    if problems:
        print("Missing labels (not guessed):\n  - " + "\n  - ".join(problems))
        return 1

    out = {}
    for config in sorted({r["config"] for r in answers}):
        traces = json.loads((AGENT / f"test_{config}_traces.json").read_text(encoding="utf-8"))
        by_q = defaultdict(list)
        for c in cites:
            if c["config"] == config:
                by_q[c["qid"]].append(as_bool(c["supports"]))
        cases, reviews = [], []
        for r in (x for x in answers if x["config"] == config):
            cases.append({"id": r["qid"], "split": "test", "answerable": bool(r["answerable"])})
            rev = {"query_id": r["qid"], "citation_support": by_q.get(r["qid"], [])}
            if r["answerable"]:
                rev["answer_grade"] = int(r["answer_grade"])
            else:
                rev["abstention_correct"] = as_bool(r["abstention_correct"])
            reviews.append(rev)
        tr = [{"query_id": t["query_id"], "status": t["status"], "events": t["events"], "citations": t["citations"]}
              for t in traces]
        d = GRADING / config
        d.mkdir(parents=True, exist_ok=True)
        for name, obj in (("cases.json", cases), ("traces.json", tr), ("reviews.json", reviews)):
            (d / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        res = subprocess.run([sys.executable, str(ROOT / "starter" / "agent_metrics.py"), "--cases", str(d / "cases.json"),
                              "--traces", str(d / "traces.json"), "--reviews", str(d / "reviews.json"),
                              "--split", "test", "--output", str(d / "agent_metrics_summary.json")],
                             capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            print(res.stderr)
            return res.returncode
        metrics = json.loads((d / "agent_metrics_summary.json").read_text(encoding="utf-8"))
        ctx = [int(r["context_score"]) for r in contexts if r["config"] == config]
        c = Counter(ctx)
        metrics["context_score"] = {"0": c[0], "1": c[1], "2": c[2], "N": len(ctx),
                                    "mean": round(sum(ctx) / len(ctx), 2) if ctx else None}
        out[config] = metrics
    (GRADING / "grading_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
