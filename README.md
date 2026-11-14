# Day 7 — Agentic RAG · Nguyễn Trường Thành (2A202603512)

Agent dùng model thật (`gpt-4.1-mini-2025-04-14`, tool calling) tìm bằng chứng trong vector store Day 6
(PostgreSQL + pgvector, *Introductory Sociology 3e*, CC BY 4.0), trả lời có citation `[chunk-id]` hoặc từ chối khi
không đủ bằng chứng. So sánh 3 phương pháp retrieval (dense, lexical, hybrid) và 7 cấu hình agent trên dev,
chốt cấu hình rồi đánh giá trên test.

- Báo cáo: [report/individual/2A202603512_NguyenTruongThanh.md](report/individual/2A202603512_NguyenTruongThanh.md)
- Thí nghiệm, giả thuyết, phân tích lỗi và quyết định (viết trước từng lần chạy): [docs/experiments.md](docs/experiments.md)
- Benchmark: [benchmark/](benchmark/README.md)

## Kết quả chính (test: 5 câu có đáp án + 2 câu thiếu bằng chứng, nhãn chấm thủ công)

| | A0 baseline (starter defaults) | **A6 đã chọn** |
|---|---|---|
| Context Evidence Rate | 0/5 | **5/5** |
| Grounded answer 0/1/2 (TB /2) | 4/1/0 (0,20) | 0/0/5 (**2,00**) |
| Citation hợp lệ | 0/1 | **7/7** |
| Abstention đúng | 2/2 | **2/2** |
| Từ chối nhầm | 4/5 | **0/5** |
| Thời gian TB / chi phí LLM | 6,26 s / $0.0078 | 2,84 s / $0.0081 |

A6 = dense + filter chương, top-3, context 2.400 ký tự, ≤4 lượt search, abstain nghiêm ngặt, citation inline bắt buộc,
cờ `context_has_exact_item`. Tập test nhỏ; xem giới hạn trong báo cáo.

## Cấu trúc

```text
benchmark/            answerable.json (20 dev + 5 test), unanswerable.json (2 dev + 2 test), absence_check.json
docs/experiments.md   cấu hình, giả thuyết, kết quả dev, lỗi dev, lựa chọn, kết quả test
src/
  export_day6.py      xuất chunk + câu hỏi từ pgvector / benchmark Day 6
  align_evidence.py   căn chỉnh evidence (chỉ khoảng trắng) sau khi chuyển schema
  check_benchmark.py  kiểm tra benchmark (evidence trong chunk, filter, số lượng, absence check)
  retrieval.py        dense / lexical / hybrid trên index Day 6
  evaluate_retrieval.py  Hit@1, Evidence Hit@3, context evidence theo ngân sách
  agent.py            vòng lặp agent: search / answer / abstain, đóng gói context, kiểm tra citation, trace
  run_agent.py        chạy một cấu hình agent trên một split, lưu trace + metrics tự động
  grading_workbook.py tạo file Excel chấm thủ công
  grade_summary.py    đọc nhãn → cases/traces/reviews → starter/agent_metrics.py
starter/              khung đề bài (agentic.py, baseline.py, convert_day6.py, agent_metrics.py)
starter/data/day7/    chunk (427, chiến lược B) và câu hỏi đã chuyển đổi
starter/results/      retrieval/, agent/, grading/ (trace, summary, nhãn)
```

## Tái lập

Cần: repo Day 6 với Docker database đã ingest ([LAB06](https://github.com/Thanhnt-da/K5-L3A-DAY06-NguyenTruongThanh-2A202603512-DataIngestion)),
đặt cạnh repo này (`../LAB06 DataIngestionEngineering`), Python 3.11+, OpenAI API key.

1. **Môi trường** (PowerShell, từ thư mục repo):
   ```bash
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   $env:PYTHONUTF8 = "1"
   ```
   `PYTHONUTF8=1` cần trên Windows để đọc/ghi JSON tiếng Việt (một test của starter đọc file không chỉ định UTF-8).
   Tạo `.env` ở thư mục gốc với `DATABASE_URL` (giống `.env` Day 6), `OPENAI_API_KEY`; không commit file này.
2. **Database Day 6:** mở Docker Desktop, rồi
   ```bash
   docker compose -f "../LAB06 DataIngestionEngineering/starter/docker-compose.yml" -p day6_student_starter up -d --wait
   ```
3. **Kiểm tra code và benchmark:**
   ```bash
   python -m unittest discover -s tests -v
   python src/export_day6.py --strategies B Z
   python starter/convert_day6.py --chunks starter/data/day6/chunks_B.json --questions starter/data/day6/questions.json --output starter/data/converted_B
   python src/align_evidence.py --dir starter/data/converted_B
   python src/check_benchmark.py
   ```
   `starter/data/day7/` (đã có trong repo) là bản sao của `converted_B`.
4. **Retrieval (dev, sau đó test khi đã chốt):**
   ```bash
   python src/evaluate_retrieval.py --split dev
   python src/evaluate_retrieval.py --split test --configs R1_dense R2_dense_filter
   ```
5. **Agent:**
   ```bash
   python src/run_agent.py --config A0_baseline --split dev        # tương tự A1_budget2400 ... A6_self_check
   python src/run_agent.py --config A0_baseline --split test
   python src/run_agent.py --config A6_self_check --split test
   ```
6. **Chấm và tổng hợp:**
   ```bash
   python src/grading_workbook.py        # tạo starter/results/grading/grading_test.xlsx (không ghi đè nếu thiếu --overwrite)
   python src/grade_summary.py           # sau khi chấm: chạy starter/agent_metrics.py cho từng cấu hình
   ```

Model chat chạy temperature 0 nhưng kết quả API có thể khác nhẹ giữa các lần chạy; trace đã lưu là kết quả được báo
cáo. Chi phí LLM toàn bộ thí nghiệm ≈ $0.15 (giá giả định $0.40/$1.60 cho 1M token vào/ra).

## Sử dụng AI

Có dùng Claude (Anthropic, Claude Code) để viết code, chạy thí nghiệm và soạn báo cáo. Câu hỏi test mới, câu thiếu
bằng chứng và toàn bộ nhãn chấm test do tác giả thực hiện; chi tiết trong báo cáo.

## Đề bài

[GUIDE.md](GUIDE.md) · [BENCHMARK.md](BENCHMARK.md) · [RUBRIC.md](RUBRIC.md) · [RULES.md](RULES.md) ·
[SUBMISSION.md](SUBMISSION.md) · [CHECKPOINTS.md](CHECKPOINTS.md) · [ADVANCED.md](ADVANCED.md) · [starter/README.md](starter/README.md)
