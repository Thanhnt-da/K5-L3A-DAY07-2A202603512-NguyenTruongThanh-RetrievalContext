"""Validate the Day 7 benchmark (no API calls, no retrieval).

- answerable: required fields; every gold evidence must be an exact substring of a chunk on the gold
  page (whitespace-only differences are fixed in place and logged); filters must exist and contain the page.
  `evidence_rule`: "any" (default, gold entries are alternatives) or "all" (every piece is required,
  e.g. evidence split across two chunks)
- unanswerable: required fields; lists every chunk containing an `absence_check_terms` entry so the
  author can confirm none of them answers the question (a human decision, not automated)
- counts: dev >= 15 answerable + 2 unanswerable; test >= 5 answerable + 2 unanswerable
- test questions must not reuse evidence used by dev questions
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark"
CHUNKS = ROOT / "starter" / "data" / "day7" / "chunks.json"
SOURCE_ID = "openstax-sociology-3e"


def ws_pattern(text: str) -> re.Pattern:
    return re.compile(r"\s+".join(re.escape(p) for p in text.split()))


def main() -> int:
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    answerable = json.loads((BENCH / "answerable.json").read_text(encoding="utf-8"))
    unanswerable = json.loads((BENCH / "unanswerable.json").read_text(encoding="utf-8"))
    problems, fixes, absence_report = [], [], []
    ids = [q.get("id") for q in answerable + unanswerable]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        problems.append(f"duplicate ids: {sorted(dupes)}")
    chapters = {c["page"]: c["metadata"]["chapter"] for c in chunks}

    for q in answerable:
        qid = q.get("id", "?")
        for key in ("id", "split", "question", "expected_answer", "gold"):
            if not q.get(key):
                problems.append(f"{qid}: missing {key}")
        if q.get("split") not in ("dev", "test"):
            problems.append(f"{qid}: split must be dev or test")
        rule = q.get("evidence_rule", "any")
        if rule not in ("any", "all"):
            problems.append(f"{qid}: evidence_rule must be 'any' (alternatives) or 'all' (every piece required)")
        if rule == "all" and len(q.get("gold", [])) < 2:
            problems.append(f"{qid}: evidence_rule 'all' needs at least 2 gold pieces")
        for g in q.get("gold", []):
            if g.get("source_id") != SOURCE_ID:
                problems.append(f"{qid}: source_id must be {SOURCE_ID}")
            same = [c for c in chunks if c["page"] == g.get("page")]
            if not same:
                problems.append(f"{qid}: page {g.get('page')} is not an indexed content page")
                continue
            if any(g["evidence"] in c["text"] for c in same):
                continue
            m = next((m for c in same for m in [ws_pattern(g["evidence"]).search(c["text"])] if m), None)
            if m:
                fixes.append({"question": qid, "page": g["page"], "before": g["evidence"], "after": m.group(0)})
                g["evidence"] = m.group(0)
            else:
                problems.append(f"{qid}: evidence not found inside one chunk on page {g['page']} "
                                "(check the quote, or it may cross a chunk boundary - pick a shorter quote)")
        for key, value in (q.get("filter") or {}).items():
            if key != "chapter":
                problems.append(f"{qid}: only a chapter filter is supported")
            elif not any(chapters.get(g.get("page")) == value for g in q.get("gold", [])):
                problems.append(f"{qid}: gold page is not inside filter chapter={value}")

    for q in unanswerable:
        qid = q.get("id", "?")
        for key in ("id", "split", "question", "absence_reason", "absence_check_terms"):
            if not q.get(key):
                problems.append(f"{qid}: missing {key}")
        if q.get("split") not in ("dev", "test"):
            problems.append(f"{qid}: split must be dev or test")
        if q.get("answerable") is not False or q.get("expected_behavior") != "search_and_abstain":
            problems.append(f"{qid}: needs answerable=false and expected_behavior=search_and_abstain")
        hits = []
        for term in q.get("absence_check_terms", []):
            for c in chunks:
                for m in re.finditer(re.escape(term), c["text"], re.I):
                    hits.append({"term": term, "chunk_id": c["id"], "page": c["page"],
                                 "snippet": c["text"][max(0, m.start() - 120):m.end() + 120].replace("\n", " ")})
        absence_report.append({"question": qid, "split": q.get("split"), "text": q.get("question"),
                               "chunks_with_terms": hits})

    dev_ev = {g["evidence"] for q in answerable if q.get("split") == "dev" for g in q.get("gold", [])}
    for q in answerable:
        if q.get("split") == "test" and any(g["evidence"] in dev_ev for g in q.get("gold", [])):
            problems.append(f"{q['id']}: test evidence is also a dev question's evidence")

    counts = {s: {"answerable": sum(q.get("split") == s for q in answerable),
                  "unanswerable": sum(q.get("split") == s for q in unanswerable)} for s in ("dev", "test")}
    for s, need in (("dev", (15, 2)), ("test", (5, 2))):
        if counts[s]["answerable"] < need[0]:
            problems.append(f"{s}: need >= {need[0]} answerable, have {counts[s]['answerable']}")
        if counts[s]["unanswerable"] < need[1]:
            problems.append(f"{s}: need >= {need[1]} unanswerable, have {counts[s]['unanswerable']}")

    if fixes:
        (BENCH / "answerable.json").write_text(json.dumps(answerable, ensure_ascii=False, indent=2), encoding="utf-8")
        log = BENCH / "evidence_whitespace_fixes.json"
        old = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
        log.write_text(json.dumps(old + fixes, ensure_ascii=False, indent=2), encoding="utf-8")
    (BENCH / "absence_check.json").write_text(json.dumps(absence_report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("counts:", counts)
    for f in fixes:
        print(f"fixed whitespace: {f['question']} p{f['page']}")
    for a in absence_report:
        print(f"absence check {a['question']} ({a['split']}): {len(a['chunks_with_terms'])} chunk hits "
              f"-> read benchmark/absence_check.json and confirm none answers it")
    if problems:
        print("PROBLEMS:\n  - " + "\n  - ".join(problems))
        return 1
    print("Benchmark OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
