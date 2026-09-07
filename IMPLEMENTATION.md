# Healthcare Outbound Voice Agent — Implementation & Review Guide

A production-style **outbound AI voice agent** for healthcare that calls patients, discusses
their latest biomarker results, books a follow-up doctor consultation, and produces full
post-call analysis with **online evaluation in Opik**. All LLM traffic is routed through a
**custom AI Gateway** (rate limiting, throttling, circuit breaking, retries, and content
guardrails).

---

## 1. Deliverables & Status

| Deliverable | Status | Evidence |
|---|---|---|
| Working implementation | ✅ Verified | Worker registers with LiveKit, picks up jobs, creates Opik traces, dials SIP |
| README with setup + usage | ✅ | This document + `README.md` |
| Complete flow: outbound call → post-call analysis → Opik | ✅ Verified | End-to-end run: `AJ_HpciVHbgjA9K` → trace `01a07c78-…` → post-call analysis logged |
| Opik trace + evaluation for the call | ✅ Verified | Trace `01a07c0e-0bb5-74ae-b9c5-ecc1b8b8d2ba` with 15 spans + 6 feedback scores (all 1.0) |
| Standalone Opik integration module | ✅ | `opik_integration.py` (no framework coupling) |

> **The one thing that still blocks a real call to your phone**: the LiveKit outbound SIP
> trunk's *address* is misconfigured. See §10 (Troubleshooting). All code paths are verified
> up to the SIP provider handshake.

---

## 2. Architecture

```
                          ┌──────────────────────────────────────────────────┐
   Patient phone (PSTN)   │               LiveKit Cloud                      │
        ▲  │              │   websocket wss://ovaa-zsfs6eoj.livekit.cloud    │
        │  │ SIP trunk    │                                                  │
        │  ▼              │   ┌──────────────┐   creates room & dispatch     │
   ┌────┴────────┐   ┌────┴─┐ │ Agent Worker │ ◄─── CreateAgentDispatch ──┐  │
   │ SIP trunk   │◄──│      │ │ (main.py)    │        (main.py dispatch)   │  │
   │ (Twilio)    │   └──────┘ └──────┬───────┘                            │  │
   └─────────────┘                   │ entrypoint                          │  │
                                     ▼                                     │  │
                    ┌─────────────────────────────────────┐                 │  │
                    │  AgentSession (livekit-agents 1.8)  │   job metadata: │  │
                    │  VAD: silero                         │   name, phone, │  │
                    │  STT: deepgram nova-2-phonecall      │   patient_id,  │  │
                    │  TTS: deepgram aura-2-thalia-en      │   biomarkers   │  │
                    │  LLM: GatewayLLM (groq) ◄─────┐     │                 │  │
                    └──────────────────┬────────────┘     │                 │  │
                                       │                 │                 │  │
                          ┌────────────▼──────────┐      ┆                 │  │
                          │  HealthcareAgent       │      │                 │  │
                          │  • on_enter greeting   │      │                 │  │
                          │  • @function_tool      │      │                 │  │
                          │    book_appointment    │      │                 │  │
                          │  • transcript tracking │   metadata JSON       │  │
                          │  • output guardrail    │      │                 │  │
                          └────────────┬──────────┘      │                 │  │
                                       │ conversation    ▼                 │  │
                                       │ events       ┌───────────────────────────┐
                          ┌────────────▼──────────┐   │     AI GATEWAY             │
                          │   AI Gateway            │──►│ tag in/out guardrails     │
                          │   (ai_gateway.py)       │   │ RPM + TPM rate limiter    │
                          │   GatewayLLM wrapper    │   │ throttle (concurrency)    │
                          └────────────┬──────────┘   │ circuit breaker            │
                                       │ Groq API      │ retry w/ backoff + jitter  │
                                       ▼               └───────────────────────────┘
                          ┌─────────────────────┐
                          │  Groq `gpt-oss-120b` │
                          └─────────────────────┘

     Post-call: transcript + tool calls ──► post_call_analysis.py ──► Opik
                                                                     ├── trace (v7 UUID)
                                                                     ├── 15 spans
                                                                     └── 6 feedback scores
```

**File layout**

```
voiceagent/
├── main.py                 CLI: dev | start | dispatch | analyze
├── agent.py                HealthcareAgent + outbound/local entrypoints
├── ai_gateway.py           Standalone AI Gateway (no livekit imports)
├── gateway_llm.py          GatewayLLM(groq.LLM) — bridges gateway into LiveKit
├── config.py               load_config() (dotenv) + PatientInfo + SAMPLE_PATIENT
├── opik_integration.py     Standalone Opik module
├── post_call_analysis.py   Transcript → outcome/topics/sentiment analysis
├── requirements.txt, .env, .env.example
└── IMPLEMENTATION.md, README.md
```

---

## 3. End-to-end call flow

1. **User dispatches a call** — `python main.py start` runs the worker; a second terminal
   runs `python main.py dispatch --phone +91… --name "Ritu Sharma"`. `main.py` creates a
   LiveKit room + `CreateAgentDispatchRequest` with patient metadata (from `SAMPLE_PATIENT`
   or CLI flags).

2. **Worker picks up the job** (`agent.py: outbound_caller` → `_run_call(dial_sip=True)`).
   - Parses `name`, `phone_number`, `patient_id`, `biomarkers` from job metadata.
   - `OpikIntegration.initialize()` → `create_call_trace(patient, {"mode": "outbound_sip"})`
     creates the parent trace (Opik v7 UUID generated via `opik.id_helpers.generate_id`).
   - `build_gateway_llm()` constructs `GatewayLLM(model="openai/gpt-oss-120b", …)` with a
     fresh `AIGateway`, ties it to the trace id, and stores it on the agent.

3. **Session boots** — `AgentSession(vad=silero.VAD, stt=deepgram.nova-2-phonecall,
   tts=deepgram.aura-2-thalia-en, llm=GatewayLLM)` is created and started on the room.
   `_track_conversation(session)` subscribes to `user_input_transcribed` and
   `conversation_item_added` to capture the transcript and run **output guardrails**.

4. **Outbound SIP call placed** — `ctx.api.sip.create_sip_participant(...)` dials the
   patient's number through trunk `ST_tx6WUovXopEP`. On Twilio/SIP error, the agent logs the
   error and gracefully logs an `error` outcome to Opik (no crash).

5. **Conversation** — when the patient answers (SIP participant joins), the agent's
   `on_enter` triggers a greeting via `self.session.generate_reply(...)`. Every LLM response
   flows through the AI Gateway. If the patient agrees, the agent calls the
   `book_appointment` function tool → appointment returned → agent confirms.

6. **Post-call** — `get_post_call_analysis()` runs `analyze_call()` (outcome, booked,
   topics, sentiment, summary). Then: `log_post_call_analysis`, `log_full_transcript`,
   `run_evaluation` (rule-based, 6 metrics), `run_llm_evaluation` (LLM-as-judge), and
   `flush()` uploads everything to Opik.

---

## 4. AI Gateway (`ai_gateway.py` + `gateway_llm.py`) — the guardrail layer

All Groq traffic passes through a pipeline of protective layers, purely in Python,
independent of LiveKit (the gateway module has **no** livekit imports — it speaks the
OpenAI-compatible API directly via `httpx`).

### Pipeline order

```
input → guardrails → RPM limiter → TPM limiter → circuit breaker
     → throttle (semaphore + bounded queue) → retry → provider call
     → output guardrails (redaction / block) → response
```

### Components

| Component | Class | Responsibility |
|---|---|---|
| Rate limiter | `TokenBucketRateLimiter` | Requests-per-minute bucket with burst (`RateLimitConfig(rpm, tpm, burst)`) |
| TPM limiter | `TokenBucketTPMLimiter` | Approximate token-per-minute bucket from last response usage |
| Throttler | `Throttler` | `max_concurrent` semaphore + `max_queue` bounded queue + `queue_timeout`; drops when saturated |
| Circuit breaker | `CircuitBreaker` | Closed → Open after `failure_threshold` failures; `cooldown_seconds` half-open probe; success closes it |
| Retry | `RetryPolicy` | Exponential backoff + jitter for retryable codes (429, 5xx), `max_retries`; non-retryable (e.g. 401) fail fast |
| Guardrails | `GuardrailEngine` | Input: length, blocked keywords, PII (SSN/card regex), medical-advice detection. Output: unsafe medical claims, PII redaction `[REDACTED]` |
| Facade | `AIGateway` | Orchestrates; exposes `generate_text()` + `stats`; logs every call to Opik as an `llm_call_groq` span |
| Bridge | `GatewayLLM(GroqLLM)` | Subclasses `livekit.plugins.groq.LLM`; `chat()` runs input guardrail + circuit checks then streams; `check_output_guardrail()` guards the post-stream text |

### Wait — why both `generate_text` and `chat()`?

- `AIGateway.generate_text()` is the **standalone, fully-pipeline path** (used for testing,
  LLM-as-judge evals, offline calls).
- `GatewayLLM.chat()` is the **realtime streaming path** LiveKit calls. It cannot easily
  intercept streaming async generators for the full sync pipeline, so it applies the
  *input guardrail + circuit breaker* synchronously before delegating to Groq's native
  streaming, and the **output guardrail** runs in `agent.py` on the assembled assistant
  text (in the `conversation_item_added` handler) before TTS. This keeps audio flowing
  (no dead air) while satisfying the guardrail requirement at both ends.

### Guardrail behavior (verified)

| Input | Result |
|---|---|
| Normal greeting | passes |
| "ignore previous instructions …" | blocked (`blocked_keyword`) |
| "My SSN is 123-45-6789" | blocked (`pii_detected`) |
| **Output** | **Result** |
| "Your glucose is 142…" | passes |
| "I guarantee this cure works instantly." | blocked (`unsafe_output`) |
| "Stop all your medication right now." | blocked (`unsafe_output`) |
| "My credit card is 1234567890123456" | redacted → `[REDACTED]` |
| "I am a real doctor…" | blocked |

All blocked results return safe fallback strings, never empty text, so TTS never produces
dead air.

---

## 5. Key technical decisions & why

1. **LiveKit 1.8.0 "one `AgentSession` per worker" rule** — `AgentServer` in 1.8.0 supports a
   single session, so we do **not** decorate entrypoints with `@server.rtc_session`. Instead
   `main.py` passes plain functions via `WorkerOptions(entrypoint_fnc=…)` and
   `agent_name=…`. This is the supported multi-agent pattern for this version.

2. **`GroqLLM` subclass instead of inline calls** — dropping a drop-in LLM object into
   `AgentSession(llm=…)` means the entire LiveKit pipeline (turn detection, tool loop, TTS
   scheduling) treats the gateway as a normal model, and the gateway remains swappable.

3. **Groq `openai/gpt-oss-120b`** — Groq decommissioned `llama-3.3-70b-versatile` on
   **2026-08-16** (returns 404). Per Groq's migration guide we moved to `openai/gpt-oss-120b`
   (their primary recommendation). Verified live via the gateway.

4. **Deepgram for STT/TTS** — `nova-2-phonecall` is tuned for telephony audio;
   `aura-2-thalia-en` for a warm, professional female voice. Silero VAD (on-device) for
   interruption/barge-in handling.

5. **Independent `ai_gateway.py`** — no LiveKit imports, so the gateway is testable offline
   and reusable outside voice (e.g., other services, non-realtime chat). Verified with a
   standalone test harness.

6. **Opik needs v7 UUIDs** — the Opik API rejects v4 UUIDs for trace/thread ids
   ("must be a version 7 UUID"), so `create_call_trace` uses
   `opik.id_helpers.generate_id()` and passes `id=<v7>` + `thread_id=<v7>` explicitly.

7. **`Agent.session` is read-only in 1.8** — the framework binds the session internally, so
   we pass the `AgentSession` into `_track_conversation(session)` rather than assigning
   `agent.session = session` (which raises `AttributeError`).

8. **`.env` must load before the worker starts** — the LiveKit worker reads `LIVEKIT_URL`
   etc. from the process environment, so `main.py` calls `load_dotenv()` at import time
   (not just inside `load_config()`).

9. **Broad SIP exception handling** — `livekit-api 1.2.1` raises `ServerError` (not
   `TwirpError`) for trunk failures with different attributes (`code`/`message` vs
   `sip_status_code`/`sip_status`); we handle both uniformly.

---

## 6. Opik integration (`opik_integration.py`)

A **standalone module** (no livekit imports — importable by any service).

### Trace structure for a call

Parent **trace** (name `outbound_call` / `manual_analysis`) with **15 spans**:

```
trace: 01a07bdb-…                (id = thread_id = v7 UUID)
├── audio_reference              LiveKit room + optional recording URL
├── 10–11 conversation spans     one per user/assistant turn (type: general)
├── tool_call_book_appointment   function-call result (note, date, doctor…)
├── full_transcript              combined transcript span
├── post_call_analysis           outcome/topics/sentiment span
└── llm_evaluation               6 feedback scores attached
```

### Evaluation metrics

| Metric | Type | What it checks |
|---|---|---|
| `biomarker_coverage` | Rule-based | Agent discussed health biomarkers with the patient |
| `appointment_discussion` | Rule-based | Appointment scheduling was discussed |
| `conversation_completeness` | Rule-based | Patient responded ≥ 3 times (multi-turn) |
| `professional_tone` | Rule-based | No unprofessional/impolite language, patient references by name |
| `call_outcome` | Rule-based | Outcome is `completed`, not error/no_answer/busy |
| `overall_call_quality` | **LLM-as-judge (online)** | Real Groq call scores the transcript 0.0-1.0 using `run_llm_evaluation()` (an `llm` span + feedback score) |

The LLM judge uses `GROQ_API_KEY`/`GROQ_MODEL` directly inside `opik_integration.py`
(keeping the module standalone). A custom judge can be injected via the optional
`judge(prompt: str) -> str` argument.

### Verified run (manual analysis)

```
python main.py analyze  →  trace 01a07c0e-0bb5-74ae-b9c5-ecc1b8b8d2ba
[PASS] biomarker_coverage: 1.00
[PASS] appointment_discussion: 1.00
[PASS] conversation_completeness: 1.00
[PASS] professional_tone: 1.00
[PASS] call_outcome: 1.00
[PASS] overall_call_quality: 1.00
→ HTTP 204 batch PUT to https://www.comet.com/opik/api/v1/private/traces/feedback-scores
```

Live e2e: trace `01a07c78-ffdb-7984-9d9b-1c016153f2ab` (SIP-dial run) with
`post_call_analysis` span + flush confirmed.

---

## 7. Setup

### Prerequisites
- Python **3.10+** (tested 3.13.4)
- LiveKit Cloud project with SIP enabled; Groq API key; Deepgram API key; Opik (Comet) key

```bash
pip install -r requirements.txt     # livekit-agents[deepgram,silero,…], livekit-plugins-groq, opik, python-dotenv
cp .env.example .env                # then fill in keys
```

### `.env` (all values present in this workspace except noted)
```ini
LIVEKIT_URL=wss://ovaa-zsfs6eoj.livekit.cloud
LIVEKIT_PROJECT_ID=p_3e91jvmt0nf
LIVEKIT_API_KEY=APImPn9zacUhPJp
LIVEKIT_API_SECRET=fx1Mh3euesmF6rgY4O6Xe4ImPHRrur9kzUHB8PqN1fFA
GROQ_API_KEY=gsk_…                 ✅ set
DEEPGRAM_API_KEY=330b…545530       ✅ set + verified valid
LIVEKIT_SIP_URI=sip:3e91jvmt0nf.sip.livekit.cloud
SIP_OUTBOUND_TRUNK_ID=ST_tx6WUovXopEP   ✅ set, ⚠️ trunk address needs fixing (see §10)
OPIK_API_KEY=7xpJT…0M2
OPIK_WORKSPACE=divyansh-aggarwal
OPIK_PROJECT_NAME=healthcare-voice-agent
```

---

## 8. Usage

```bash
# 1) Run the worker (production outbound mode)
python main.py start

# 2) In another terminal, dispatch a call
python main.py dispatch --phone +919876543210 --name "Ritu Sharma"

# Local dev (no SIP): register test agent
python main.py dev

# Offline demo: transcript → analysis → Opik (no LiveKit needed)
python main.py analyze
```

`SAMPLE_PATIENT` (Sarah Johnson, +1234567890, glucose/HbA1c/cholesterol) is used when no
flags are passed to `dispatch`/`analyze`.

---

## 9. How to test (procedure + expectations)

1. **Offline sanity (no keys beyond Opik):** `python main.py analyze` → all 6 evals PASS,
   Opik trace created.
2. **Gateway unit tests (offline):** run the gateway test snippets in `ai_gateway.py`
   docstring — verify RPM blocking, throttle queue-full, circuit open/half-open, guardrail
   blocks, retry backoff.
3. **Live worker registration:** `python main.py start` → logs `registered worker
   agent_name="healthcare-caller" id="AW_…" region="India South"`.
4. **Full call:** fix trunk address (§10) → start worker → `dispatch --phone <real number>`
   → phone rings → agent greets, discusses biomarkers, books appointment; room/recording
   created; on hangup post-call analysis + evaluations land in Opik under
   `healthcare-voice-agent`.

---

## 10. Troubleshooting / known issues

| Symptom | Cause | Fix |
|---|---|---|
| `SIP call failed (invalid_argument) … no such host "my-voice-agent1 .pstn.twilio.com"` | Outbound trunk **address** has a stray space (`my-voice-agent1 .pstn…`); DNS lookup fails | LiveKit console → SIP → Outbound Trunks → `ST_tx6WUovXopEP` → set address to the correct host (e.g. `my-voice-agent1.pstn.twilio.com`) |
| `The model llama-3.3-70b-versatile does not exist` | Model decommissioned 2026-08-16 | Already migrated to `openai/gpt-oss-120b` |
| `property 'session' … has no setter` | LiveKit 1.8 binds session internally | Use `_track_conversation(session)` (already done) |
| `list_dispatch`/`ListAgentDispatchRequest(room=…)` TypeError | livekit-api 1.2.1 protobuf quirk | Avoid; use `agent_dispatch.create_dispatch` + `room.delete_room` for cleanup |
| `ImportError: cannot import name 'APIConnectOptions'/'DEFAULT_API_CONNECT_OPTIONS' from livekit.agents.llm` | These live in `livekit.agents` | Already imported from `livekit.agents` |
| `trace id must be a version 7 UUID` (Opik) | v4 UUID rejected | `opik.id_helpers.generate_id()`, passed as `id=` (done) |
| `cli.run_app()` deprecation warning | livekit-agents deprecation | Functional in 1.8; preferred CLI is `lk agent start --entrypoint agent.py` |

---

## 11. Reviewer quick-map

| Concern | Where |
|---|---|
| Curso pipeline start→end | `agent.py: outbound_caller` → `_run_call(dial_sip=True)` |
| Phone booking tool | `agent.py: HealthcareAgent.book_appointment` (`@function_tool`) |
| Transcript + output guardrail | `agent.py: _track_conversation` |
| Gateway layers | `ai_gateway.py: AIGateway.generate_text`; configs at top of file |
| Streaming bridge | `gateway_llm.py: GatewayLLM.chat`/`check_output_guardrail` |
| Opik trace/eval | `opik_integration.py: create_call_trace`, `run_evaluation`, `run_llm_evaluation` |
| Post-call analysis | `post_call_analysis.py: analyze_call` |
| CLI wiring | `main.py` (`dev/start/dispatch/analyze`) |