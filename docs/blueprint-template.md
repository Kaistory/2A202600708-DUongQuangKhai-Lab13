# Day 13 Observability Lab Report

> **Instruction**: Fill in all sections below. This report is designed to be parsed by an automated grading assistant. Ensure all tags (e.g., `[GROUP_NAME]`) are preserved.
>
> **Submission type: SOLO** — all roles were completed by a single person. Team
> member slots B–E are intentionally marked `N/A (solo submission)`.

## 1. Team Metadata
- [GROUP_NAME]: Solo Submission — Dương Quang Khải
- [REPO_URL]: https://github.com/Kaistory/Lab13-Observability-DUongQuangKhai-2A202600708
- [MEMBERS]:
  - Member A: Dương Quang Khải | Role: ALL (Logging & PII, Tracing & Enrichment, SLO & Alerts, Load Test & Dashboard, Demo & Report)
  - Member B: N/A (solo submission)
  - Member C: N/A (solo submission)
  - Member D: N/A (solo submission)
  - Member E: N/A (solo submission)

---

## 2. Group Performance (Auto-Verified)
- [VALIDATE_LOGS_FINAL_SCORE]: 70/100
- [TOTAL_TRACES_COUNT]: 88 (Langfuse project `Lab13`, us.cloud.langfuse.com; grows on each run)
- [PII_LEAKS_FOUND]: 1 (in the `request_failed` event — see Known Issues in §6)

> `scripts/validate_logs.py` output: 1111 log records analysed, 0 missing
> required fields, 0 missing enrichment, 532 unique correlation IDs, 1 PII hit.
> Score is 70/100 because of the single PII leak on the error path.

---

## 3. Technical Evidence (Group)

### 3.1 Logging & Tracing
- [EVIDENCE_CORRELATION_ID_SCREENSHOT]: data/logs.jsonl — every `service:"api"` record carries a unique `correlation_id` (e.g. `req-11b60e7c`); 532 unique IDs across 1111 records (verified by `scripts/validate_logs.py`). Set in `app/middleware.py` (CorrelationIdMiddleware).
- [EVIDENCE_PII_REDACTION_SCREENSHOT]: data/logs.jsonl — message previews show `[REDACTED_EMAIL]` and `[REDACTED_PHONE_VN]` (scrubber in `app/logging_config.py` / `app/pii.py`). Example: input `"... My email is student@vinuni.edu.vn"` is logged as `"... My email is [REDACTED_EMAIL]"`.
- [EVIDENCE_TRACE_WATERFALL_SCREENSHOT]: img/langfuse_error_traces.png (Langfuse Tracing view, observations list)
- [TRACE_WATERFALL_EXPLANATION]: Each `/chat` trace is a root span **`run`** (the agent pipeline) with two child spans: **`retrieve`** (RAG) and **`generate`** (LLM). The most interesting span is `retrieve`: under the `rag_slow` incident it balloons from a few ms to ~2.5s (`time.sleep(2.5)`), so the trace immediately localizes the latency to the retrieval step rather than the LLM — exactly what tracing is for.

### 3.2 Dashboard & SLOs
- [DASHBOARD_6_PANELS_SCREENSHOT]: img/dashboard_grid.png and img/dashboard_grid_bottom.png (Langfuse custom dashboard "Lab13 — Observability (6-Panel)", arranged as a 3×3 grid: latency p50/p95/p99 · traffic/errors/cost · tokens/quality)
- [SLO_TABLE]:
| SLI | Target | Window | Current Value |
|---|---:|---|---:|
| Latency P95 | < 3000ms | 28d | 151ms (baseline) — breaches to ~2652ms under `rag_slow` |
| Error Rate | < 2% | 28d | 0% (baseline) — spikes to 100% under `tool_fail` |
| Cost Budget | < $2.5/day | 1d | ~$0.0021/req (≈$0.02 per 10-request run) — well under budget |

> Current values captured from `GET /metrics`:
> `{"traffic":10,"latency_p50":151,"latency_p95":151,"latency_p99":151,"avg_cost_usd":0.0021,"total_cost_usd":0.0214,"tokens_in_total":340,"tokens_out_total":1360,"error_breakdown":{},"quality_avg":0.88}`

### 3.3 Alerts & Runbook
- [ALERT_RULES_SCREENSHOT]: config/alert_rules.yaml (4 SLO-aligned rules) + img/alert_test_output.txt (automated `scripts/test_alerts.py` run: all 4 scenarios PASS)
- [SAMPLE_RUNBOOK_LINK]: docs/alerts.md#2-high-error-rate

> Alert rules configured (thresholds tied to config/slo.yaml):
> | Alert | Condition | Severity |
> |---|---|---|
> | high_latency_p95 | latency_p95_ms > 2000 | P2 |
> | high_error_rate | error_rate_pct > 5 | P1 |
> | cost_budget_spike | avg_cost_usd > 0.004 | P2 |
> | low_quality_score | quality_avg < 0.75 | P3 |
>
> Tested with `scripts/check_alerts.py` (operator CLI, exits 1 when firing) and
> `scripts/test_alerts.py` (boots an isolated app per incident and asserts the
> expected alert fires). Result: 4/4 scenarios PASS.

---

## 4. Incident Response (Group)
- [SCENARIO_NAME]: tool_fail (vector store / retrieval tool failure)
- [SYMPTOMS_OBSERVED]: Every `/chat` request returns HTTP 500; `error_rate_pct` jumps from 0% to 100%; the `high_error_rate` (P1) alert fires; latency/cost/quality read "no-data" because no request completes successfully.
- [ROOT_CAUSE_PROVED_BY]: Langfuse shows 8 observations with `level=ERROR` and `status_message="Vector store timeout"` on the `retrieve` and `run` spans (queried via the Langfuse API). Matching log lines: `event:"request_failed"`, `error_type:"RuntimeError"`, `payload.detail:"Vector store timeout"` in data/logs.jsonl. Root cause: `app/mock_rag.py:retrieve()` raises `RuntimeError("Vector store timeout")` when the `tool_fail` toggle is on.
- [FIX_ACTION]: Disable the failing tool toggle (`POST /incidents/tool_fail/disable`); in production, fail over to a backup retrieval source or serve a graceful fallback answer instead of a 500.
- [PREVENTIVE_MEASURE]: Add a retry-with-timeout + circuit breaker around the retrieval call, and keep the `high_error_rate` P1 alert (error_rate_pct > 5% for 5m) so the regression pages on-call within minutes.

> A second incident, `rag_slow`, was also exercised: the `retrieve` span grows to
> ~2652ms and trips the `high_latency_p95` (P2) alert — see img/alert_test_output.txt.

---

## 5. Individual Contributions & Evidence

### Dương Quang Khải (solo — all roles)
- [TASKS_COMPLETED]:
  - **Logging & PII**: structured JSON logging, correlation-ID middleware (`app/middleware.py`), PII scrubber (`app/logging_config.py`, `app/pii.py`).
  - **Tracing & Enrichment**: Langfuse `@observe` instrumentation (`app/agent.py`, `app/tracing.py`), context enrichment (user/session/feature/model). Fixed a Langfuse host misconfiguration in `.env` (`LANGFUSE_BASE_URL` → `LANGFUSE_HOST`) that was silently dropping all traces (auth failed against the wrong region).
  - **SLO & Alerts**: configured `config/alert_rules.yaml` (4 SLO-aligned rules + runbook §4 in `docs/alerts.md`); built `scripts/check_alerts.py` (alert engine/CLI) and `scripts/test_alerts.py` (automated 4-scenario test). All scenarios pass.
  - **Load Test & Dashboard**: ran `scripts/load_test.py`; built the 6-panel Langfuse dashboard and arranged it as a clean 3×3 grid.
  - **Demo & Report**: this report + evidence in `img/`.
- [EVIDENCE_LINK]: https://github.com/Kaistory/Lab13-Observability-DUongQuangKhai-2A202600708/commits/main — key files: `config/alert_rules.yaml`, `scripts/check_alerts.py`, `scripts/test_alerts.py`, `app/agent.py`, `app/tracing.py`, `app/middleware.py`, `app/logging_config.py`, `docs/alerts.md`, `img/`.

### [MEMBER_B_NAME]
- [TASKS_COMPLETED]: N/A (solo submission)
- [EVIDENCE_LINK]: N/A

### [MEMBER_C_NAME]
- [TASKS_COMPLETED]: N/A (solo submission)
- [EVIDENCE_LINK]: N/A

### [MEMBER_D_NAME]
- [TASKS_COMPLETED]: N/A (solo submission)
- [EVIDENCE_LINK]: N/A

### [MEMBER_E_NAME]
- [TASKS_COMPLETED]: N/A (solo submission)
- [EVIDENCE_LINK]: N/A

---

## 6. Bonus Items (Optional)
- [BONUS_COST_OPTIMIZATION]: Cost panel + `cost_budget_spike` alert (avg_cost_usd > $0.004, ~2× the ~$0.002/req baseline) detect the `cost_spike` incident, where output tokens 4× and avg cost rises to ~$0.0084/req. Evidence: img/alert_test_output.txt.
- [BONUS_AUDIT_LOGS]: Not implemented (`data/audit.jsonl` hook available but unused).
- [BONUS_CUSTOM_METRIC]: `quality_avg` heuristic quality score exposed via `/metrics` and guarded by the `low_quality_score` (P3) alert at the 0.75 SLO.

---

## Known Issues / Honest Caveats
1. **PII leak on the error path (score 70/100)**: 1 of 1111 log records (a `request_failed` event) trips the PII check. The error logging path needs the same scrubbing as the success path.
2. **Cost & Tokens panels empty in Langfuse**: `app/agent.py` attaches `usage_details` to a *span* via `update_current_observation`; the v2→v3 shim in `app/tracing.py` drops `usage_details` for spans (only generations accept it), so token/cost usage never reaches Langfuse. The in-process `/metrics` values are correct; only the Langfuse-derived panels are blank. Fix: emit usage on a generation observation.
3. **Quality panel empty in Langfuse**: the heuristic `quality_score` is recorded in `/metrics` but never emitted as a Langfuse score. Fix: `score_current_trace(name="quality", value=...)` in `app/agent.py`.
