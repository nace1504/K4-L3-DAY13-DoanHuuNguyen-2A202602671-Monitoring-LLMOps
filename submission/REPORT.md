# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Doãn Hữu Nguyên
- **MSSV:** 2A202602671
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/nace1504/K4-L3-DAY13-DoanHuuNguyen-2A202602671-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602671`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | [`01-pytest-cp2c.txt`](evidence/01-pytest-cp2c.txt) |
| Log validator | `evidence/02-log-validator.txt` |
| Dashboard validator | [`03-dashboard-validator.txt`](evidence/03-dashboard-validator.txt) |
| Structured log | `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.txt` |
| Trace list | [`06-trace-list.png`](evidence/06-trace-list.png) (lọc `name:lab-agent-run`, Total 41 trace), [`06b-trace-list-columns.png`](evidence/06b-trace-list-columns.png), [`06-trace-list.txt`](evidence/06-trace-list.txt) |
| Trace waterfall | [`07-trace-waterfall.png`](evidence/07-trace-waterfall.png) (trace `9e18aad4fcb5f47130d5cbf02013d15d`: `lab-agent-run` 152 ms → `retrieval` 0 ms + `llm-generation` 151 ms) |
| Trace metadata | [`08-trace-metadata.png`](evidence/08-trace-metadata.png) (root: `correlation_id=req-50ee8a6a`, prompt `day13-chat` v1 `production`), [`08b-generation-metadata.png`](evidence/08b-generation-metadata.png) (model, 213 tokens, $0.002775), [`08-trace-metadata.txt`](evidence/08-trace-metadata.txt). Dòng `scope.attributes.public_key` do SDK tự gắn đã được che đen |
| Prompt versions | `evidence/09a-prompt-v1-production-baseline.png`, `evidence/09b-prompt-v2-candidate.png` |
| Prompt rollback | [`10a-prompt-promote.png`](evidence/10a-prompt-promote.png) (production → v2), [`10b-prompt-rollback.png`](evidence/10b-prompt-rollback.png) (production → v1), [`10-prompt-rollback.txt`](evidence/10-prompt-rollback.txt) |
| Dashboard runtime | [`11-dashboard-overview.png`](evidence/11-dashboard-overview.png) (sinh bằng `python scripts/build_dashboard.py` từ `data/logs.jsonl`, cửa sổ 60 phút 03:16–04:16 UTC, 71 request) |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 ([log](evidence/baseline/baseline-validate-logs.txt)) | 100/100 ([log](evidence/02-log-validator.txt)) | 20/21 record thiếu required field và enrichment; `correlation_id` MISSING (0 unique ID) do middleware chưa sinh/bind context vào logger. CP1: 0 record thiếu field, 11 correlation ID (10 load test + 1 PII test) |
| `validate_dashboard.py` | 6/6 ([log](evidence/baseline/baseline-validate-dashboard.txt)) | 6/6 ([log](evidence/03-dashboard-validator.txt)) | Dashboard contract đủ 6 panel; dashboard runtime vẽ đúng 6 panel theo contract ([ảnh](evidence/11-dashboard-overview.png)) |
| `pytest` | 22 passed ([log](evidence/baseline/baseline-pytest.txt)) | 36 passed ([log](evidence/01-pytest-cp2c.txt)) | +14 test: PII (CCCD, thẻ, passport, câu 4 loại), middleware, child observations, hàm tổng hợp của dashboard |
| Số traces hợp lệ | chưa tính (chưa có child span, prompt fallback) | 20/20 ([list](evidence/06-trace-list.txt)) | Baseline: prompt `day13-chat` (label `production`) trả 404 → `local-fallback`. CP2a: 20 trace từ 2 lần load test, trace nào cũng có `lab-agent-run → {retrieval, llm-generation}`, `prompt_source=langfuse`, v1, generation có model/usage/cost, không có PII thô |
| Số PII leak | 0 ([log](evidence/baseline/baseline-validate-logs.txt)) | 0 ([log](evidence/05-pii-redaction.txt)) | Baseline 0 chỉ vì load test không có PII lọt qua `summarize_text`; CP1 đã test với request chứa đủ 4 loại PII giả |
| Latency P95 / TTFT P95 | 1863 ms / 50 ms ([metrics](evidence/baseline/baseline-metrics.txt)) | 6185 ms / 50 ms ([dashboard](evidence/11-dashboard-overview.png), 71 request trong 60 phút); riêng 50 request load test: 152 ms / 50 ms | Baseline: 10 request; P50 585 ms; mỗi request tốn thêm 1 lần gọi Langfuse do không cache được prompt. Cuối: P95 của cửa sổ vượt 3000 ms vì 9 request CP2b bị chậm (3909–11566 ms) do fetch prompt đầu tiên sau restart timeout; khi đã cache prompt, P95 còn khoảng 152 ms |
| Retrieval success rate | 100% (10/10) ([metrics](evidence/baseline/baseline-metrics.txt)) | 100% (71/71, [dashboard](evidence/11-dashboard-overview.png)) | Không bật incident; error rate 0% (0 `request_failed`) |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` gọi `clear_contextvars()` đầu mỗi request, nhận header `x-request-id` nếu khớp `^[A-Za-z0-9._-]{1,64}$`, ngược lại sinh `req-<8 hex>`. ID được `bind_contextvars` (structlog tự gắn vào mọi log line qua `merge_contextvars`), lưu vào `request.state.correlation_id` để truyền cho agent/response body, và trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`; context từ `chat()`: `user_id_hash` (SHA-256 cắt 12 ký tự, không log `user_id` thô), `session_id`, `feature`, `model`, `env`; với `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in/out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** `scrub_event` được đăng ký trong chuỗi processor của structlog sau `TimeStamper` và trước `JsonlFileProcessor()`/`JSONRenderer()`. Processor chạy tuần tự, nên event dict đã được che trước khi được ghi xuống file hay stdout. Nó scrub mọi giá trị string ở top-level (trừ `ts`, `level`, `correlation_id`, `user_id_hash`, `session_id`) và đệ quy trong dict/list như `payload`. Pattern: email, thẻ, CCCD, SĐT VN, passport VN, xếp theo thứ tự email trước, rồi số dài trước số ngắn.
- **Cách kiểm chứng kết quả:** `pytest` (30 passed, gồm `tests/test_pii.py` và `tests/test_middleware.py` mới); `scripts/validate_logs.py` đạt 100/100 trên log mới của load test + 1 request PII giả (`req-pii00001`); `grep` 4 chuỗi PII gốc trong `data/logs.jsonl` đều 0 lần xuất hiện.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** Dùng key của project `day13-k4-l3b-2A202602671` (nạp từ `.env`) để query Langfuse `GET /api/public/v2/observations` từ thời điểm bắt đầu load test (2026-09-30T03:08:49Z). Kết quả có 20 trace; `metadata.correlation_id` của từng trace khớp với các ID `req-xxxxxxxx` mà `scripts/load_test.py` in ra và với `data/logs.jsonl` ([06](evidence/06-trace-list.txt)).
- **Cấu trúc root/retrieval/generation observations:** Trace `day13-agent-request` (đặt tên qua `propagate_attributes`) có root observation `lab-agent-run` (AGENT), mang metadata prompt name/label/version/source, `doc_count`, `query_preview`. Root có 2 con: `retrieval` (RETRIEVER, bọc `retrieve()`) và `llm-generation` (GENERATION, bọc `FakeLLM.generate`). Generation nhận `model`, `usage_details` input/output, `cost_details` input/output/total (đơn giá $3/$15 mỗi 1M token), link tới managed prompt, và input/output đã qua `summarize_text` (scrub PII). Input/output của hai observation con đều tắt auto-capture ([08](evidence/08-trace-metadata.txt)).
- **Cách nối trace với log:** Correlation ID từ middleware được truyền vào `LabAgent.run` rồi vào metadata của trace qua `propagate_attributes`, nên cùng một ID xuất hiện ở cả log lẫn mọi observation. Ví dụ: trace `9e18aad4fcb5f47130d5cbf02013d15d` ↔ `correlation_id=req-50ee8a6a`. Dòng `response_sent` trong `data/logs.jsonl` có `tokens_in=35`, `tokens_out=178`, `cost_usd=0.002775`, khớp đúng `usageDetails` và `costDetails.total` của generation ([08](evidence/08-trace-metadata.txt)).
- **Prompt name:** `day13-chat`
- **Version/label baseline:** v1 — `baseline`, `production`
- **Version/label candidate:** v2 — `candidate`
- **Trace ID của mỗi version:** Cùng một input, chỉ đổi label: v1 (`baseline`) → trace `618f8b03284480cd00e7e9db16cf38cf` (`req-cp2b-base4`, tokens_in=35); v2 (`candidate`) → trace `d2781bc812137e102351cfe9084ea34c` (`req-cp2b-cand5`, tokens_in=50, dài hơn vì v2 có thêm một dòng hướng dẫn) ([10](evidence/10-prompt-rollback.txt)).
- **Cách promote và rollback `production`:** App chỉ hỏi Langfuse `get_prompt(name, label=LANGFUSE_PROMPT_LABEL)`, nên promote hay rollback đều là chuyển label `production` sang version khác trên Langfuse UI, không cần sửa code hay deploy. Prompt được cache 60 giây trong process. Sau khi hết TTL, SDK vẫn trả bản cũ (stale) trong lúc refresh nền, nên phải chờ hết cache cộng thêm một request, hoặc restart. Chứng minh bằng 3 trace cùng input với label `production`: `210cb201102ea70f6838cb9be77efc91` (`req-cp2b-prod1`, v1) → promote → `520149704ae014b7b3113d4834d27c60` (`req-cp2b-promote`, v2) → rollback → `fc437654b400758e76a2ea91734c78d0` (`req-cp2b-rollback2`, v1). Request `req-cp2b-rollback` ngay sau khi hết TTL vẫn nhận v2 (stale), điều này cũng được ghi trong evidence ([10a](evidence/10a-prompt-promote.png), [10b](evidence/10b-prompt-rollback.png), [10](evidence/10-prompt-rollback.txt)).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `scripts/build_dashboard.py` (matplotlib) đọc duy nhất `data/logs.jsonl`, lấy title, `time_range_minutes`=60, `refresh_seconds`=30 và threshold từ `config/dashboard.yaml`. Percentile dùng lại `app.metrics.percentile`. Nó xuất lưới 3×2 ra `evidence/11-dashboard-overview.png` (2100×1150 px, `--watch` để vẽ lại mỗi 30 giây) và in bảng OK/BREACH. Sáu panel: (1) Latency P50/P95/P99 + TTFT P95 theo phút, ngưỡng P95 ≤ 3000 ms; (2) Traffic request/phút, ngưỡng ≥ 1; (3) Error rate %, breakdown `error_type` và retrieval success %, ngưỡng ≤ 2%; (4) Cost theo phút và cộng dồn, ngưỡng tổng ≤ $2.5; (5) Tổng tokens in/out, ngưỡng ≤ 50,000; (6) Quality trung bình, ngưỡng ≥ 0.75. Cửa sổ 03:16–04:16 UTC (10:16–11:16 giờ VN): 71 request, P95 6185 ms (BREACH), 1.18 req/phút, error 0%, retrieval 100%, cost $0.1476, tokens 2,682/9,304, quality 0.856.
- **SLO và lý do chọn:** `fast_successful_requests`: 99.5% request có `response_sent` với `latency_ms <= 3000` trong 28 ngày (`config/slo.yaml`). Mock FakeLLM chỉ mất khoảng 152 ms (P95), nhưng tôi vẫn giữ 3000 ms vì LLM thật thường cần vài giây; ngưỡng này phản ánh trải nghiệm người dùng chấp nhận được, không phải tốc độ của mock. SLI dựa trên triệu chứng (chậm hoặc lỗi), không dựa trên chi tiết implementation.
- **Cách tính error budget:** Budget = (100% − 99.5%) × số request = 0.5% × tổng `request_received`. Bad event = request không có `response_sent` trong ngưỡng: chậm hơn 3000 ms, hoặc `request_failed` (có trong total nhưng không bao giờ là good). Số thật trong `data/logs.jsonl`: 102 request, 93 good, 9 bad (đều là request CP2b chậm do fetch prompt timeout), 0 failed. Good = 91.18% < 99.5%; budget chỉ là 0.51 request, nên đã cạn (khoảng 17.6 lần budget). Quy mô ví dụ: 10,000 request trong 28 ngày thì tối đa 50 request được phép lỗi hoặc chậm.
- **Ba alert và runbook tương ứng:** Định nghĩa trong `config/alert_rules.yaml` (symptom-based, Slack `#k4-l3b-alerts`, owner `student-2A202602671`): (1) `HighLatencyP95` warning: `p95(response_sent.latency_ms) > 3000` trong 5m, [runbook](../docs/alerts.md#alert-1); (2) `HighErrorRate` critical: `error_rate_pct > 2 or retrieval_success_pct < 90` trong 5m, [runbook](../docs/alerts.md#alert-2); (3) `CostSpike` warning: `sum(cost_usd) per 1h > 2x baseline hourly cost or avg(tokens_out) > 400` trong 10m, [runbook](../docs/alerts.md#alert-3). Runbook nào cũng đi theo thứ tự dashboard → lọc log lấy `correlation_id` → trace Langfuse, và có mitigation cụ thể (so span retrieval với generation, tắt incident, rollback prompt, fallback context, retry/circuit breaker, giới hạn `max_tokens`).

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** SDK Langfuse tự gắn `scope.attributes.public_key` (cùng các thuộc tính OTel `resourceAttributes.*`) vào metadata của mọi observation. Khi xuất metadata trace ra evidence text, tôi lọc bỏ `scope.*`/`resourceAttributes.*`/`public_key`, và che key trong ảnh chụp, vì quy định cấm screenshot/evidence lộ public hay secret key.
- **Một lỗi/blocker đã gặp:** Mọi request đều log `Prompt not found: 'day13-chat' with label 'production'` (404) nên app dùng `prompt_source=local-fallback`; vì prompt không được cache, mỗi request tốn thêm một lần gọi Langfuse, làm tăng latency. (2) Ở CP2b, mạng tới `cloud.langfuse.com` chập chờn, nên lần fetch prompt đầu tiên sau restart vượt `fetch_timeout_seconds=2` và rơi về `local-fallback`. App vẫn trả 200 và metadata ghi rõ `prompt_source`. Ngoài ra, OTLP span export bị timeout nên mất một số trace: 21 request thì 8 trace mất và 4 lần fallback, tất cả đều ghi trong [10](evidence/10-prompt-rollback.txt).
- **Cách tìm nguyên nhân và xử lý:** Đọc log uvicorn khi chạy load test baseline, thấy lỗi 404 lặp lại ở từng request. Sẽ xử lý ở CP2b bằng cách tạo prompt `day13-chat` với label `production` trên project Langfuse cá nhân. Lỗi 404 đã hết sau khi tạo prompt `day13-chat` (v1 production/baseline, v2 candidate) trên Langfuse. (2) Log uvicorn có `Error while fetching prompt ...: timed out` và `Failed to export spans batch due to timeout`. Tôi đo trực tiếp `get_prompt` với timeout dài thì thấy kết nối đầu tiên mất 8–64 giây, các lần sau chỉ khoảng 1 giây. Cách xử lý: gửi request warm-up sau mỗi lần restart; đổi label dựa vào cache TTL 60 giây thay vì restart; kiểm tra trace đã lên Langfuse rồi mới tắt server, vì `taskkill /F` bỏ qua bước flush.
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
