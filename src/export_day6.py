"""Export the Day 6 pgvector index and benchmark into Day 6-style JSON arrays.

Reads chunks straight from the Day 6 PostgreSQL + pgvector database (no re-embedding) and
the Day 6 questions file. Output is then converted to the Day 7 contract with
starter/convert_day6.py.

Run from the repo root:
    .venv/Scripts/python.exe src/export_day6.py --strategies B Z
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DAY6 = ROOT.parent / "LAB06 DataIngestionEngineering"
DEFAULT_QUESTIONS = DAY6 / "benchmark" / "questions.jsonl"
OUT = ROOT / "starter" / "data" / "day6"


def export_chunks(conn, strategy: str) -> list[dict]:
    rows = conn.execute(
        "SELECT chunk_id, document_id, source, page, page_end, printed_page, chapter, section, "
        "section_title, content FROM chunks WHERE strategy = %s ORDER BY page, chunk_id", (strategy,)).fetchall()
    if not rows:
        raise SystemExit(f"Strategy {strategy} has no chunks in the Day 6 database")
    return [{"chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3], "text": r[9],
             "metadata": {"day6_strategy": strategy, "page_end": r[4] or r[3], "printed_page": r[5],
                          "chapter": r[6], "section": r[7], "section_title": r[8]}} for r in rows]


def export_questions(path: Path) -> list[dict]:
    """Keep Day 6 dev/test questions; build `gold` with every documented alternative.

    Cross-page probe questions (split 'probe', gold_page is a list) are written to a
    separate file because the Day 7 contract needs evidence inside one chunk on one page.
    """
    main, probes = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        gold = [{"source_id": q["gold_source_id"], "page": q["gold_page"], "evidence": q["evidence_quote"]}]
        gold += [{"source_id": g["source_id"], "page": g["page"], "evidence": g["evidence_quote"]}
                 for g in q.get("alternative_gold", [])]
        out = {"id": q["id"], "split": q["split"], "type": q.get("type"), "question": q["question"],
               "expected_answer": q["expected_answer"], "gold": gold}
        if q.get("filter"):
            out["filter"] = q["filter"]
        (probes if q["split"] == "probe" else main).append(out)
    return main, probes


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Day 6 chunks + questions to JSON")
    parser.add_argument("--strategies", nargs="+", default=["B", "Z"])
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing in .env")
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(url, connect_timeout=5) as conn:
        for s in args.strategies:
            chunks = export_chunks(conn, s)
            (OUT / f"chunks_{s}.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"strategy {s}: {len(chunks)} chunks -> {(OUT / f'chunks_{s}.json').relative_to(ROOT)}")
    main_q, probes = export_questions(args.questions)
    (OUT / "questions.json").write_text(json.dumps(main_q, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "probe_questions.json").write_text(json.dumps(probes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"questions: {len(main_q)} dev/test, {len(probes)} probe")


if __name__ == "__main__":
    main()
