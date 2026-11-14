"""Generate the manual grading workbook for the test runs (baseline A0 + chosen A6).

The script fills context columns only; every label is left empty for the human grader.
    PYTHONUTF8=1 .venv/Scripts/python.exe src/grading_workbook.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from retrieval import Day6Index  # noqa: E402

AGENT = ROOT / "starter" / "results" / "agent"
BENCH = ROOT / "benchmark"
OUT = ROOT / "starter" / "results" / "grading" / "grading_test.xlsx"

GREY = PatternFill("solid", fgColor="E7E6E6")
YELLOW = PatternFill("solid", fgColor="FFF2CC")
HEAD = PatternFill("solid", fgColor="1F4E78")
NOTE = PatternFill("solid", fgColor="DDEBF7")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

ANSWER_RUBRIC = ("Answerable questions: 0 = wrong, or missing the needed evidence; 1 = partly correct (missing a "
                 "condition, number or part of a two-part question); 2 = correct and complete. An abstention on an "
                 "answerable question is graded 0.")
ABSTAIN_RUBRIC = ("Unanswerable questions: TRUE = the agent really refused and added no unsupported claim; FALSE = it "
                  "answered, guessed, or hedged with claims.")
CITATION_RUBRIC = ("TRUE = the cited chunk really supports the sentence(s) it is attached to, incl. its conditions; "
                   "FALSE = it does not, or only partly. A valid chunk id is NOT enough - read it.")
CONTEXT_RUBRIC = ("0 = no evidence for the answer in the final context; 1 = evidence present but a condition or the "
                  "source is missing (or only one of two required pieces); 2 = enough evidence and source to answer.")


def header(ws, cols, banner):
    ws.append([banner])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    ws["A1"].fill, ws["A1"].alignment, ws["A1"].font = NOTE, WRAP, Font(bold=True)
    ws.row_dimensions[1].height = 80
    ws.append([c[0] for c in cols])
    for i, (name, width, kind, note) in enumerate(cols, start=1):
        cell = ws.cell(row=2, column=i)
        cell.fill, cell.font, cell.alignment, cell.border = HEAD, Font(bold=True, color="FFFFFF"), WRAP, BORDER
        ws.column_dimensions[get_column_letter(i)].width = width
        cell.comment = Comment(("YOU fill this.\n" if kind == "input" else "Filled by script.\n") + note,
                               "grading", width=320, height=150)
    ws.freeze_panes = "A3"


def style(ws, cols):
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row):
        for cell, (_, _, kind, _) in zip(row, cols):
            cell.alignment, cell.border = WRAP, BORDER
            cell.fill = YELLOW if kind == "input" else GREY


def dropdown(ws, col, options, rows=None):
    dv = DataValidation(type="list", formula1=f'"{options}"', allow_blank=True, showErrorMessage=True,
                        error=f"Choose one of: {options}")
    ws.add_data_validation(dv)
    dv.add(f"{col}3:{col}{max(ws.max_row, 3)}" if rows is None else rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", nargs="+", default=["A0_baseline", "A6_self_check"])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if OUT.exists() and not args.overwrite:
        raise SystemExit(f"{OUT.name} exists (it may hold your labels). Use --overwrite to replace it.")
    gold = {q["id"]: q for q in json.loads((BENCH / "answerable.json").read_text(encoding="utf-8"))}
    gold.update({q["id"]: q for q in json.loads((BENCH / "unanswerable.json").read_text(encoding="utf-8"))})
    traces = {c: json.loads((AGENT / f"test_{c}_traces.json").read_text(encoding="utf-8")) for c in args.configs}
    index = Day6Index()
    all_ids = sorted({i for c in traces for t in traces[c] for i in t.get("citations", [])})
    chunk = {r["chunk_id"]: r for r in index._rows(
        "SELECT chunk_id, page, section, content FROM chunks WHERE strategy = %(s)s AND chunk_id = ANY(%(ids)s)",
        {"s": index.strategy, "ids": all_ids})} if all_ids else {}

    wb = Workbook()
    g = wb.active
    g.title = "0_Guide"
    g.column_dimensions["A"].width = 24
    g.column_dimensions["B"].width = 110
    for a, b in [
        ("GRADING WORKBOOK", f"Day 7 test split, configs {', '.join(args.configs)} (baseline + chosen). All labels are "
                             "yours (human). Grey = script, yellow = you fill. Do not rename sheets or columns."),
        ("How", "Use the dropdowns, write a one-line reason. Compare with expected_answer and gold_evidence, and read "
                "the cited chunk text. Save as .xlsx, then tell Claude 'grading done'."),
        ("", ""),
        ("1_Answers", ANSWER_RUBRIC), ("", ABSTAIN_RUBRIC),
        ("  Note", "A refusal on an answerable question = grade 0 (the sheet pre-marks status). Fill answer_grade for "
                   "answerable rows and abstention_correct for unanswerable rows; leave the other one empty."),
        ("2_Citations", CITATION_RUBRIC),
        ("3_Context", CONTEXT_RUBRIC),
        ("  Note", "t02 needs BOTH pieces (capital flight definition AND deindustrialization sentence) for a 2."),
        ("", ""),
        ("Bias", "The grader is also the author of the system and benchmark; say so in the report."),
    ]:
        g.append([a, b])
    for row in g.iter_rows():
        for cell in row:
            cell.alignment = WRAP
        if row[0].value and not str(row[0].value).startswith("  "):
            row[0].font = Font(bold=True)
    g["A1"].font = Font(bold=True, size=14)

    # ---- answers
    ws = wb.create_sheet("1_Answers")
    cols = [("row_id", 8, "auto", ""), ("config", 14, "auto", ""), ("qid", 6, "auto", ""),
            ("answerable", 9, "auto", ""), ("question", 36, "auto", ""), ("expected_answer", 34, "auto", ""),
            ("gold_evidence", 45, "auto", "Gold evidence (any one for 'any'; all pieces for t02)."),
            ("status", 9, "auto", "answered / abstain"), ("agent_answer", 55, "auto", ""),
            ("citations", 24, "auto", ""), ("searches", 7, "auto", ""),
            ("answer_grade", 9, "input", ANSWER_RUBRIC), ("abstention_correct", 10, "input", ABSTAIN_RUBRIC),
            ("reason", 45, "input", "One line: why.")]
    header(ws, cols, "ANSWERS - is the final answer correct (answerable) / is the refusal real (unanswerable)?\n"
           + ANSWER_RUBRIC + "\n" + ABSTAIN_RUBRIC)
    n = 0
    for c in args.configs:
        for t in traces[c]:
            q = gold[t["query_id"]]
            n += 1
            ev = "\n---\n".join(f"p{p['page']}: {p['evidence']}" for p in q.get("gold", []))
            if q.get("evidence_rule") == "all":
                ev = "ALL pieces required:\n" + ev
            ws.append([f"ans{n:03d}", c, t["query_id"], bool(q.get("answerable", True)), q["question"],
                       q.get("expected_answer", q.get("absence_reason", "")), ev or f"(none) {q.get('absence_reason','')}",
                       t["status"], t["answer"], "\n".join(t.get("citations", [])), t.get("searches"),
                       None, None, None])
    style(ws, cols)
    dropdown(ws, "L", "0,1,2")
    dropdown(ws, "M", "TRUE,FALSE")

    # ---- citations
    ws2 = wb.create_sheet("2_Citations")
    ccols = [("row_id", 8, "auto", ""), ("config", 14, "auto", ""), ("qid", 6, "auto", ""),
             ("question", 30, "auto", ""), ("agent_answer", 50, "auto", "Find the sentence carrying this citation."),
             ("cited_chunk", 24, "auto", ""), ("page", 6, "auto", ""), ("cited_chunk_text", 70, "auto", "Read this."),
             ("supports", 9, "input", CITATION_RUBRIC), ("note", 40, "input", "Why / what is missing.")]
    header(ws2, ccols, "CITATIONS - does each cited chunk really support the sentence it is attached to?\n" + CITATION_RUBRIC)
    m = 0
    for c in args.configs:
        for t in traces[c]:
            for cid in t.get("citations", []):
                m += 1
                ch = chunk.get(cid, {})
                ws2.append([f"cit{m:03d}", c, t["query_id"], t["question"], t["answer"], cid, ch.get("page"),
                            ch.get("content", "(chunk text not found)"), None, None])
    style(ws2, ccols)
    dropdown(ws2, "I", "TRUE,FALSE")

    # ---- context
    ws3 = wb.create_sheet("3_Context")
    xcols = [("row_id", 8, "auto", ""), ("config", 14, "auto", ""), ("qid", 6, "auto", ""),
             ("question", 32, "auto", ""), ("gold_evidence", 40, "auto", ""),
             ("auto_context_evidence", 9, "auto", "Script: gold evidence string found in final context."),
             ("final_context", 80, "auto", "Exactly what the model saw last."),
             ("context_score", 9, "input", CONTEXT_RUBRIC), ("reason", 40, "input", "One line: why.")]
    header(ws3, xcols, "CONTEXT - is there enough evidence (and source) in the final context sent to the model?\n" + CONTEXT_RUBRIC)
    k = 0
    for c in args.configs:
        for t in traces[c]:
            q = gold[t["query_id"]]
            if not q.get("answerable", True):
                continue
            k += 1
            ev = "\n---\n".join(f"p{p['page']}: {p['evidence']}" for p in q["gold"])
            ws3.append([f"ctx{k:03d}", c, t["query_id"], q["question"], ev, bool(t.get("context_evidence")),
                        t.get("final_context") or "(empty)", None, None])
    style(ws3, xcols)
    dropdown(ws3, "H", "0,1,2")

    p = wb.create_sheet("9_Progress")
    p.append(["sheet", "label column", "rows", "filled"])
    for name, col, total in (("1_Answers", "L", n), ("1_Answers", "M", n), ("2_Citations", "I", m), ("3_Context", "H", k)):
        r = p.max_row + 1
        p.append([name, col, total, f"=COUNTA('{name}'!{col}3:{col}{total + 2})"])
    for cell in p[1]:
        cell.fill, cell.font = HEAD, Font(bold=True, color="FFFFFF")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"Wrote {OUT.relative_to(ROOT)}: answers {n} rows, citations {m} rows, context {k} rows")


if __name__ == "__main__":
    main()
