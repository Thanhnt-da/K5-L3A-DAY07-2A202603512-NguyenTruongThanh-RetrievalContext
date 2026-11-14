# Day 7 agent experiments (written before the full dev runs)

Model `gpt-4.1-mini-2025-04-14`, temperature 0; index = Day 6 strategy B (427 chunks, pgvector, cosine);
query embeddings `text-embedding-3-small`. Same 22 dev questions (20 answerable + 2 unanswerable) for every config.
Context budget = characters of the packed context incl. `[id | source | page]` headers (starter rule: keep order,
skip duplicates and chunks that do not fit).

| Config | Change vs previous | Hypothesis |
|---|---|---|
| A0_baseline | starter defaults: dense, top-3/search, 800 chars, ≤4 searches, no filter | Weak: in Step 3 only 3/20 dev questions had evidence inside an 800-char context; expect many false abstentions. |
| A1_budget2400 | budget 800 → 2400 | Context Evidence Rate rises toward the Step 3 value (19/20), so answered-with-citation rises sharply; unanswerable abstention should stay 2/2. |
| A2_filter | A1 + chapter filter when the question gives one | Fixes wrong-chapter context on q05, q10, q20 (Step 3: dense Hit@1 13→15 with filter); no change elsewhere. |
| A3_hybrid | A2 with hybrid RRF retrieval (dense weight 0.75, Day 6 value, not re-tuned) | Better Hit@1 on exact-term questions; may lose some paraphrase questions (Step 3: lexical missed q03, q13). |
| A4_diverse_queries | A2 + prompt rule: a follow-up search must use different key terms | Fewer repeated near-identical searches (q01 smoke test), helping questions whose first query misses (e.g. q08). |

## Dev failure analysis after A0–A4 (added before running A5)

Results A0–A4 (dev, 20 answerable + 2 unanswerable): A0 abstains on almost everything (context evidence 4/20).
A1–A4 reach context evidence 18–19/20 but **answer both unanswerable questions (0/2)** and lose 5–7 answerable
questions to the citation safeguard.

1. **Partial answer instead of abstention (u01, u02).** The model writes "…are not named in the provided context.
   However, …" and calls `answer` with related facts (Walmart / The Children's Place; poverty lines for 1, 2 and 4
   people) instead of `abstain`. Cause: the prompt says to abstain when evidence is missing, but the `answer` tool
   still accepts a hedged answer about a neighbouring fact.
2. **Missing inline citations → false abstention (A2: q01, q08, q09, q10, q17, q18).** Evidence was in the
   context and the answer text looks right, but the model put the id only in the `citations` array, not as `[id]`
   in the text, so the safeguard rejected it. Cause: the citation format is stated once in the system prompt and not
   in the tool schema.

| Config | Change vs A2 | Hypothesis |
|---|---|---|
| A5_strict_cite | A2 + (a) rule and tool description: if the exact item asked for (name, number, year, group) is not in CONTEXT, call `abstain` - never answer with "not stated, however…"; (b) the `answer` tool description requires every citation to appear inline as `[id]`, with an example | Unanswerable abstention back to 2/2 (fixes failure 1) and most of the 6 citation rejections become valid answers (fixes failure 2), while context evidence stays 19/20. Risk: stricter abstention may also refuse some answerable questions. |

The citation safeguard itself is **not** relaxed: a citation still has to be in the final context and inline.

**A5 result (dev):** answered with valid citations 19/20 (was 14/20 in A2), context evidence 19/20, 1 citation
rejection (q04); unanswerable 1/2 - u01 now abstains, **u02 still gives a hedged partial answer** ("…for a
household of six is not explicitly stated… However, … $26,500 for a family of four").

| Config | Change vs A5 | Hypothesis |
|---|---|---|
| A6_self_check | A5 + the `answer` tool has a required boolean `context_has_exact_item`; when the model sets it to `false` the code records an abstention (event `self_reported_missing`) instead of trusting the prompt alone | u02 becomes an abstention (2/2) because the model already states the item is missing; answerable questions unaffected (≥18/20 answered). Caveat: only 2 dev unanswerable questions, so this is tuned on a tiny sample - the test set (u03, u04) is the real check. |

## Dev results (all configs, 20 answerable + 2 unanswerable, 0 system errors)

| Config | Context Evidence Rate | Answered w/ valid citations | Unanswerable abstained | Citation rejections | Searches (n: count) | LLM cost (USD) | Median s/question |
|---|---|---|---|---|---|---|---|
| A0_baseline | 4/20 | 4/20 | 2/2 | 2 | 1:5, 3:3, 4:14 | 0.0221 | 5.25 |
| A1_budget2400 | 18/20 | 15/20 | 0/2 | 5 | 1:21, 2:1 | 0.0161 | 2.51 |
| A2_filter | 19/20 | 14/20 | 0/2 | 6 | 1:21, 2:1 | 0.0163 | 2.42 |
| A3_hybrid | 18/20 | 13/20 | 0/2 | 7 | 1:19, 2:2, 4:1 | 0.0175 | 2.49 |
| A4_diverse_queries | 19/20 | 14/20 | 0/2 | 6 | 1:21, 2:1 | 0.0171 | 2.87 |
| A5_strict_cite | 19/20 | 19/20 | 1/2 | 1 | 1:20, 2:1, 3:1 | 0.0207 | 2.59 |
| A6_self_check | 19/20 | 19/20 | 2/2 | 1 | 1:19, 2:1, 3:2 | 0.0227 | 2.65 |

Notes: the larger budget is what made the agent usable (A0→A1); the filter added context evidence (18→19); hybrid
(A3) and the query-diversity rule (A4) did not help here - with a 2,400-char context the agent almost always stops
after one search, so query diversity rarely comes into play. Remaining dev failure: q04 (TANF) - the answer lists a
chunk id but cites it inline incompletely, so the safeguard rejects it; q08 still answered from the right page.

## Choice (made on dev, before any test run)

Applying the rule: only **A0** and **A6** satisfy the hard constraint (unanswerable 2/2, no errors). A6 has the
higher Context Evidence Rate (19/20 vs 4/20) and more valid answers (19/20 vs 4/20). **Chosen: A6_self_check.**
Test will run **A0_baseline** (baseline) and **A6_self_check** (chosen) once each, then be graded manually.
Caveat: A5/A6 were designed after reading dev failures, and only 2 unanswerable dev questions exist, so the test
unanswerable questions (u03, u04) are the independent check of the abstention fix.

## Selection rule (fixed before the runs)

1. **Hard constraint:** no system errors and unanswerable abstention 2/2 on dev; a config that answers an
   unanswerable dev question is not selected.
2. Highest dev **Context Evidence Rate** (evidence in the final context).
3. Then most answerable questions **answered with valid citations** (status `answered`), i.e. fewest false abstentions.
4. Then lower LLM cost, then lower median latency.

Automatic proxies are used for selection on dev; answer correctness, citation support and abstention are graded
by the author on test (baseline A0 and the chosen config), as BENCHMARK.md requires. At least two dev failures are
read and explained before choosing.
