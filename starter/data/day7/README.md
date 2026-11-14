# Day 7 working dataset

- Index: Day 6 strategy **B** chunks (paragraph-aware, max 1000 chars, one page per chunk), 427 chunks,
  exported from the Day 6 pgvector table by `src/export_day6.py`, converted with `starter/convert_day6.py`.
  Strategy **C** = same chunks + `chapter` filter. Dense search queries the Day 6 pgvector rows directly.
- Questions: Day 6 dev/test questions converted to the Day 7 schema; whitespace-only evidence alignment
  logged in `evidence_alignment_log.json` (q05).
- Why B and not Z (Day 6's choice): Day 7 citations/hits need evidence inside one chunk on one page;
  13/46 two-page Z chunks have over-wide ranges and q18's evidence sits in a Z chunk tagged p341.
