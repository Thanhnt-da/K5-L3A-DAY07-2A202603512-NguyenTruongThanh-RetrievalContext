# Day 7 benchmark

Corpus: OpenStax *Introductory Sociology 3e*, chapters 9–12 (PDF pages 269–410), indexed as Day 6 strategy **B**
chunks (427, one page each). `page` = physical PDF page. `source_id` is always `openstax-sociology-3e`.

| File | Contents |
|---|---|
| `answerable.json` | Questions with an answer. q01–q20 come from Day 6 (all **dev** now; q16–q20 were Day 6's test). **Add 5 new `test` questions here.** |
| `unanswerable.json` | Questions with no answer in the corpus. **Add ≥2 `dev` and ≥2 `test`.** |

Required counts: dev ≥15 answerable + ≥2 unanswerable; test ≥5 answerable + ≥2 unanswerable.
Write the new test questions **before** any Day 7 retrieval/agent run, and do not change them afterwards.

## New answerable test question (append to `answerable.json`)

```json
{"id": "t01", "split": "test", "type": "direct", "answerable": true, "origin": "day7-new",
 "question": "your question, in your own words",
 "expected_answer": "short correct answer",
 "gold": [{"source_id": "openstax-sociology-3e", "page": 303,
           "evidence": "exact sentence copied from that page"}]}
```

- `gold` may list several alternatives (any one counts). Each `evidence` must be copied **exactly** from one chunk
  on that page (copy from the PDF; the checker accepts differences in spaces/line breaks and fixes them).
- Optional `"filter": {"chapter": 10}` only if the question's context gives the chapter.
- `"evidence_rule": "all"` marks a question whose evidence is split across chunks: every `gold` piece is
  required (default `"any"` = alternatives). Used by **t02** (two chunks on p307). Such questions count as a hit /
  context hit only when all pieces are present and are also reported separately. Note: the starter's
  `baseline.py` treats `gold` as alternatives, so for t02 use `src/` evaluation, not the starter metric.
- Do not reuse a Day 6 question or its evidence with new wording.

## Unanswerable question (append to `unanswerable.json`)

```json
{"id": "u01", "split": "dev", "answerable": false, "expected_behavior": "search_and_abstain",
 "question": "near-topic question whose answer is NOT in chapters 9-12",
 "absence_reason": "why the corpus cannot answer it (e.g. topic only defined, value never given)",
 "absence_check_terms": ["key", "terms", "to search"]}
```

- Prefer questions close to the book's topics (a tempting nearby passage makes a better test).
- `absence_check_terms`: words or phrases the checker searches for in all 427 chunks. It lists every chunk that
  contains one, so you can read them and confirm none answers the question. A hit is not automatically a failure.

## Check

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe src/check_benchmark.py
```
