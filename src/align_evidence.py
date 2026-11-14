"""Whitespace-only alignment of gold evidence to the chunk text (Day 7 needs exact substrings).

Day 6 matched evidence ignoring punctuation/whitespace; Day 7's baseline checks
`evidence in chunk['text']` exactly. When a quote spans two paragraphs, the chunk holds
"\\n\\n" where the quote holds a space. This script replaces such an evidence string with the
exact chunk span ONLY if the two differ in whitespace alone (words and punctuation identical).
Every change is logged; anything else is reported and left untouched.

    .venv/Scripts/python.exe src/align_evidence.py --dir starter/data/converted_B
"""
import argparse
import json
import re
from pathlib import Path


def whitespace_regex(evidence: str) -> re.Pattern:
    parts = [re.escape(p) for p in evidence.split()]
    return re.compile(r"\s+".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()
    chunks = json.loads((args.dir / "chunks.json").read_text(encoding="utf-8"))
    qpath = args.dir / "questions.json"
    questions = json.loads(qpath.read_text(encoding="utf-8"))
    log = []
    for q in questions:
        for g in q["gold"]:
            same = [c for c in chunks if c["source_id"] == g["source_id"] and c["page"] == g["page"]]
            if any(g["evidence"] in c["text"] for c in same):
                continue
            pattern = whitespace_regex(g["evidence"])
            match = next((m for c in same for m in [pattern.search(c["text"])] if m), None)
            if match:
                log.append({"question": q["id"], "page": g["page"], "change": "whitespace only",
                            "before": g["evidence"], "after": match.group(0)})
                g["evidence"] = match.group(0)
            else:
                log.append({"question": q["id"], "page": g["page"], "change": "NONE - no chunk on this page "
                            "holds the evidence even ignoring whitespace (left unchanged)"})
    qpath.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.dir / "evidence_alignment_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n",
                                                          encoding="utf-8")
    for entry in log:
        print(entry["question"], "p", entry["page"], "->", entry["change"])
    print(f"{len(log)} evidence entries needed attention")


if __name__ == "__main__":
    main()
