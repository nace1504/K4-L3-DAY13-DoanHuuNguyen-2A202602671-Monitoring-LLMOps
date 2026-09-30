# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms` (panel "Latency percentiles and TTFT"); SLO `fast_successful_requests` 99.5% request có `latency_ms <= 3000` trong 28 ngày (`config/slo.yaml`)
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms) > 3000` kéo dài liên tục 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ nhiều giây mới nhận được câu trả lời; mỗi request chậm hơn 3000 ms đều trừ vào error budget
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard (`python scripts/build_dashboard.py`, ảnh `submission/evidence/11-dashboard-overview.png`) để xác nhận P95/P99 tăng từ phút nào, TTFT P95 có tăng theo không, traffic có tăng đột biến không.
  2. Lọc `data/logs.jsonl` trong khoảng đó: lấy `event == "response_sent"` có `latency_ms > 3000`, ghi lại `correlation_id`, `feature`, `model`.
  3. Mở trace cùng `correlation_id` trên Langfuse (metadata `correlation_id`), so sánh latency của span `retrieval` với `llm-generation`, và xem `prompt_version`/`prompt_source`/`prompt_fetch_error` trên root `lab-agent-run`.
- Mitigation tạm thời:
  - Nếu span `retrieval` chậm: kiểm tra `GET /health` → `incidents.rag_slow`; tắt bằng `POST /incidents/rag_slow/disable` hoặc giảm tải (hạ concurrency khi demo).
  - Nếu `llm-generation` chậm sau khi đổi prompt: rollback label `production` về version trước trên Langfuse (có hiệu lực sau TTL cache 60s).
  - Nếu root chậm nhưng hai span con nhanh, và `prompt_source=local-fallback`: đây là prompt fetch timeout. Kiểm tra kết nối tới Langfuse và warm-up sau restart.
- Owner: `student-2A202602671`

## Alert 2

- Tên: `HighErrorRate`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: error rate = `request_failed / request_received × 100` và retrieval success = `tool_success == true / tool_success != null` (panel "Error rate and retrieval success"); guardrail `error_rate_pct_max: 2`, `retrieval_success_rate_pct_min: 90`; mỗi `request_failed` là bad event của SLO
- Điều kiện và thời gian duy trì: `error_rate_pct > 2 or retrieval_success_pct < 90` kéo dài liên tục 5 phút
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 (không có câu trả lời) hoặc câu trả lời thiếu context tài liệu; error budget cạn rất nhanh
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard, xem panel Errors: error rate và retrieval success từ phút nào, breakdown `error_type` là gì.
  2. Lọc `data/logs.jsonl`: `event == "request_failed"`, đếm theo `error_type`, `tool_name`, `tool_success`; lấy một `correlation_id` đại diện và đọc `payload.detail`.
  3. Mở trace cùng `correlation_id` trên Langfuse: span nào có level ERROR (`retrieval` hay `llm-generation`), status message là gì.
- Mitigation tạm thời:
  - Nếu lỗi ở `retrieval` (ví dụ `RuntimeError: Vector store timeout`): kiểm tra `GET /health` → `incidents.tool_fail`, tắt bằng `POST /incidents/tool_fail/disable`; tạm thời trả lời bằng fallback context ("No domain document matched…") thay vì 500.
  - Bật retry có backoff cho retrieval và circuit breaker (ngắt gọi vector store khi lỗi liên tiếp, trả fallback) để tránh dồn tải.
  - Nếu lỗi xuất hiện ngay sau khi đổi prompt: rollback label `production`.
- Owner: `student-2A202602671`

## Alert 3

- Tên: `CostSpike`
- Severity: `warning`
- Duration: `10m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: `sum(cost_usd)` theo giờ và `avg(tokens_out)` của `response_sent` (panel "Cost over time", "Input and output tokens"); guardrail `daily_cost_usd_max: 2.5`. Baseline hourly cost lấy từ một giờ bình thường trên dashboard (ví dụ cửa sổ 60 phút ngày 2026-09-30: $0.1476 cho 71 request). FakeLLM bình thường sinh 80–180 `tokens_out`, nên `avg(tokens_out) > 400` là bất thường.
- Điều kiện và thời gian duy trì: `sum(cost_usd) per 1h > 2x baseline hourly cost or avg(tokens_out) > 400` kéo dài liên tục 10 phút
- Ảnh hưởng tới người dùng: câu trả lời dài dòng hơn, chậm hơn; chi phí vận hành tăng và có nguy cơ vượt ngân sách ngày
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard: cost theo phút và tokens_out tăng từ lúc nào, traffic có tăng cùng lúc không (tăng do tải hay do mỗi request đắt hơn).
  2. Lọc `data/logs.jsonl`: `event == "response_sent"` có `tokens_out` cao, so với các request trước đó; lấy `correlation_id`, `feature`.
  3. Mở trace cùng `correlation_id` trên Langfuse: so `usage` và `cost` của `llm-generation`, `prompt_version` trên root và generation, so với trace trước khi cost tăng.
- Mitigation tạm thời:
  - So `tokens_out` và `prompt_version` trước và sau khi tăng: nếu tăng sau khi promote prompt mới thì rollback label `production` về version cũ.
  - Kiểm tra `GET /health` → `incidents.cost_spike`, tắt bằng `POST /incidents/cost_spike/disable`.
  - Giới hạn `max_tokens` cho generation và rate-limit theo user/feature cho tới khi tìm ra nguyên nhân.
- Owner: `student-2A202602671`
