# Healthcare Outbound Voice Agent

An AI-powered outbound voice agent built with LiveKit that calls patients to discuss health biomarkers and schedule doctor consultations, with full observability (tracing + online evaluation) via Opik.

> **Review guide:** see [`IMPLEMENTATION.md`](IMPLEMENTATION.md) for the full architecture,
> technical decisions, verified end-to-end flow, and troubleshooting.

## Quick Start

```bash
pip install -r requirements.txt   # install dependencies
cp .env.example .env              # add your API keys (see .env.example)
                                  # Windows: Copy-Item .env.example .env

python main.py analyze            # demo pipeline → Opik trace (no LiveKit needed)
python main.py dev                # local test worker (talk to the agent via LiveKit playground)
python main.py call --phone "+1234567890" --name "Sarah"   # one-command outbound call
python main.py start              # production outbound worker only (requires SIP trunk)
python main.py dispatch --phone "+1234567890" --name "Sarah"   # schedule a call (worker must be running)
```

## Architecture

```
main.py                 → CLI entry point (dev/start/call/dispatch/analyze)
├── agent.py            → LiveKit HealthcareAgent + shared call flow (_run_call)
├── ai_gateway.py       → Standalone AI Gateway (rate limit, throttle, circuit breaker, retry, guardrails)
├── gateway_llm.py      → LiveKit bridge: GatewayLLM(groq.LLM) routing through the gateway
├── config.py           → Configuration, env vars, PatientInfo data model, SAMPLE_PATIENT
├── opik_integration.py → Standalone Opik module (tracing, logging, evaluation)
├── post_call_analysis.py → Transcript analysis and outcome determination
├── demo.py             → Sample transcript/tool-call data for `python main.py analyze`
└── .env.example        → Environment variable template
```

### Call Flow

```
Dispatch → LiveKit Room → SIP Outbound Call → Patient Answers
    → Agent discusses biomarkers → Agent offers appointment
    → book_appointment tool called → Appointment confirmed
    → Call ends → Post-call analysis → Opik trace + evaluation
```

## Setup

### 1. Prerequisites

- Python 3.10+
- LiveKit Cloud account (or self-hosted) with SIP enabled
- Groq API key
- Deepgram API key
- Opik account (Comet Cloud or self-hosted)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
# macOS / Linux
cp .env.example .env

# Windows (PowerShell)
Copy-Item .env.example .env
```

The `.env` file is loaded automatically (`load_dotenv()` in `main.py`).

Required variables:
- `LIVEKIT_URL` - Your LiveKit project WebSocket URL
- `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` - LiveKit API credentials
- `GROQ_API_KEY` - Groq API key for the LLM (routed through the AI Gateway)
- `DEEPGRAM_API_KEY` - Deepgram API key for STT/TTS
- `OPIK_API_KEY` - Opik API key (from Comet Cloud)
- `OPIK_WORKSPACE` - Opik workspace name
- `OPIK_PROJECT_NAME` - Opik project name (default: `healthcare-voice-agent`)

For outbound calling, set:
- `SIP_OUTBOUND_TRUNK_ID` - Your LiveKit SIP outbound trunk ID (used by `agent.py` to dial)
- `LIVEKIT_SIP_URI` - Informational: your project's SIP URI (e.g., `sip:3e91jvmt0nf.sip.livekit.cloud`), used for SIP trunk registration in the LiveKit console — **not** read by this code

Optional:
- `CALL_RECORDING_URL` - URL of the recorded call audio (e.g. a LiveKit Egress URL).
  When unset, only the LiveKit room name is logged to Opik.
- `GROQ_MODEL` - Model used by the LLM-as-judge evaluation (defaults to `openai/gpt-oss-120b`).

### 4. SIP Trunk Setup (Outbound Calling)

Create an outbound SIP trunk via the LiveKit CLI:

```bash
# Create trunk config file
cat > sip-trunk.json << EOF
{
  "trunk": {
    "name": "Healthcare Outbound",
    "address": "your-sip-provider.pstn.example.com",
    "numbers": ["+1XXXXXXXXXX"],
    "auth_username": "your-sip-user",
    "auth_password": "your-sip-password"
  }
}
EOF

# Create the trunk
lk sip outbound create sip-trunk.json
```

Then set the resulting trunk ID in your `.env`:
```
SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxx
```

## Usage

### Local Development (No SIP Required)

Test the agent without making real phone calls. The agent starts speaking when a participant connects:

```bash
python main.py dev
```

Then connect via the LiveKit playground or your own client to interact with the agent.

> Note: `python main.py dev`/`start` use the legacy Python runner (`cli.run_app`). For the
> recommended production runner, install the `lk` CLI
> (https://github.com/livekit/livekit-cli) and run:
> `lk agent start --entrypoint agent.py` (configure agent name via `LIVEKIT_AGENT_NAME`).

### Production Outbound Calling

**Option A — one command (recommended for a single call):**

`call` starts the worker in a background thread, waits for it to register with
LiveKit Cloud, dispatches the call, and stays alive until the call ends — so the
whole flow runs from a single terminal:

```bash
python main.py call \
  --phone "+1234567890" \
  --name "Sarah Johnson" \
  --patient-id "PT-2024-0042"
```

> There is no way around the fact that LiveKit's worker is a **long-running
> process** and a dispatch is a **separate API call** — the worker must be
> registered before LiveKit can route a job to it. `call` simply orchestrates
> both inside one process so you don't need two terminals.
>
> - `--worker-wait <seconds>` controls how long to wait for the worker to
>   register before dispatching (default `8`). Raise it if the worker is slow
>   to connect.
> - `--detach` runs the worker as a separate subprocess instead of a background
>   thread (useful if the in-process thread conflicts with your environment).

**Option B — separate terminals (long-running worker):**

1. Start the agent worker:

```bash
python main.py start
```

2. Dispatch a call to a patient:

```bash
python main.py dispatch \
  --phone "+1234567890" \
  --name "Sarah Johnson" \
  --patient-id "PT-2024-0042"
```

> `dispatch` is **fire-and-forget**: it schedules the job and exits. The call then runs
> asynchronously inside the worker, so the outcome appears in the **worker log**
> (`Call completed. Analysis: ...`) and in the **Opik trace** (`post_call_analysis` span
> + feedback scores).

Or dispatch programmatically:

```python
import asyncio
from livekit import api

async def dispatch_call():
    async with api.LiveKitAPI() as lkapi:
        await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="healthcare-caller",
                room="new-room",
                metadata='{"name": "Sarah Johnson", "phone_number": "+1234567890", "patient_id": "PT-2024-0042", "biomarkers": {"Blood Glucose": {"value": 142, "unit": "mg/dL", "reference_range": "70-100", "status": "HIGH"}}}',
            )
        )

asyncio.run(dispatch_call())
```

### Run Demo Analysis (No LiveKit Required)

Run the complete analysis pipeline with sample data to see Opik integration:

```bash
python main.py analyze
```

This creates a trace in Opik with:
- Call metadata and variables (patient, biomarkers, mode)
- Audio reference (LiveKit room name + optional recording URL)
- Sample conversation transcript (individual turns + full transcript)
- Simulated appointment booking tool call
- Post-call analysis
- Evaluation results (biomarker coverage, appointment discussion, conversation completeness, professional tone, call outcome, LLM-as-judge quality score)

## Modules

### `opik_integration.py` - Standalone Opik Module

This is a self-contained module that can be plugged into any LiveKit project. It provides:

- **`OpikIntegration`** class with methods for:
  - `create_call_trace()` - Create a trace for a call (metadata + variables)
  - `log_audio_reference()` - Log call audio/recording reference (room name + optional URL)
  - `log_conversation_item()` - Log individual conversation turns
  - `log_full_transcript()` - Log complete transcript
  - `log_tool_call()` - Log function/tool calls with arguments and results
  - `log_post_call_analysis()` - Log analysis results
  - `run_evaluation()` - Run rule-based evaluation metrics
  - `run_llm_evaluation()` - Run a real LLM-as-judge evaluation (online)

- **Data classes**: `ConversationTurn`, `ToolCallRecord`, `PostCallAnalysis`, `EvaluationResult`

### `agent.py` - Healthcare Agent

The LiveKit agent that:
- Extends the `Agent` base class
- Discusses health biomarkers in patient-friendly language
- Uses `@function_tool` for appointment booking
- Captures conversation transcript via session events
- Triggers post-call analysis and Opik logging

### `post_call_analysis.py` - Post-Call Analysis

Analyzes the call to determine:
- Call outcome (completed, no_answer, busy, error)
- Whether an appointment was booked
- Key topics discussed (glucose, HbA1c, cholesterol, etc.)
- Overall sentiment
- Human-readable summary

## AI Gateway (`ai_gateway.py` + `gateway_llm.py`)

A proper guardrail layer sits in front of the Groq LLM. `gateway_llm.py` exposes
`GatewayLLM`, a subclass of `livekit.plugins.groq.LLM` that is dropped into the
`AgentSession(llm=...)` unchanged. Every LLM request flows through the pipeline:

```
user message
   → Input guardrails (length, blocked keywords, PII, medical-safety ping)
   → Rate limiter    (RPM token bucket, TPM limiter)
   → Circuit breaker (open on repeated failures, half-open probes)
   → Throttler       (max concurrent + bounded queue)
   → Retry           (exponential backoff + jitter on 429/5xx)
   → Groq API (openai/gpt-oss-120b)
   → Output guardrails (unsafe claims, PII redaction, max length)
   → TTS
```

Components (`ai_gateway.py`):

| Component | Class | What it does |
|-----------|-------|--------------|
| Rate limiter | `TokenBucketRateLimiter` | Requests-per-minute bucket with burst |
| TPM limiter | `TokenBucketTPMLimiter` | Approximate tokens-per-minute cap |
| Throttler | `Throttler` | `max_concurrent` + bounded queue + timeout |
| Circuit breaker | `CircuitBreaker` | Fails open/half-open/closed states with cooldown |
| Retry | `RetryPolicy` | Exponential backoff + jitter for transient errors |
| Guardrails | `GuardrailEngine` | Input/output content checks, PII redaction |
| Facade | `AIGateway` | Orchestrates the pipeline, exposes `generate_text()` |
| LiveKit bridge | `GatewayLLM` | `GroqLLM` subclass; `chat()` intercepts for guardrails |

Gateways are configurable:

```python
from ai_gateway import GatewayConfig, RateLimitConfig, ThrottleConfig, GuardrailConfig

llm = GatewayLLM(
    model="openai/gpt-oss-120b",
    api_key="gsk_...",
    gateway_config=GatewayConfig(
        rate_limit=RateLimitConfig(rpm=20, tpm=200_000, burst=5),
        throttle=ThrottleConfig(max_concurrent=5, max_queue=10, queue_timeout=30.0),
        guardrails=GuardrailConfig(max_input_length=4000, max_output_length=4000),
    ),
)
session = AgentSession(llm=llm, ...)
```

Blocked/rate-limited/circuit-open responses return safe fallback strings (never empty
audio), and repeated provider failures trip the circuit breaker so the call degrades
gracefully instead of hammering the provider.

## Opik Evaluations

The system implements 6 evaluation metrics, all logged as **feedback scores** on each
call's Opik trace:

| Metric | Type | Description |
|--------|------|-------------|
| `biomarker_coverage` | Rule-based | Did the agent discuss health biomarkers? |
| `appointment_discussion` | Rule-based | Did the agent attempt scheduling? |
| `conversation_completeness` | Rule-based | Minimum user responses exchanged |
| `professional_tone` | Rule-based | No unprofessional language detected |
| `call_outcome` | Rule-based | Appropriate call handling |
| `overall_call_quality` | **LLM-as-judge (online)** | Real Groq call scores the call 0.0-1.0 |

The LLM-as-judge (`run_llm_evaluation()`) runs automatically after every completed call
inside `opik_integration.py` — it calls Groq with the transcript + analysis, parses the
model's `SCORE:`/`REASON:`, and logs an `llm` evaluation span plus the feedback score.
This is the **online evaluation** required by the assignment; the rule-based metrics run
in the same pass.

Rule-based scores and the LLM-judge score are all viewable in the Opik dashboard. Optionally,
you can also configure Opik **Automation Rules** in the UI to run alongside them:
1. Go to your Opik project → Automation Rules
2. Create a new rule with the criteria above
3. Set sampling rate (e.g., 100% for initial testing)
4. Rules will automatically score incoming production traces

## Opik Trace Structure

Each call creates a trace in Opik with this structure:

```
outbound_healthcare_call (Trace)
├── audio_reference (Span)
├── conversation_user (Span)        × N turns
├── conversation_assistant (Span)   × N turns
├── tool_call_book_appointment (Span)
├── full_transcript (Span)
├── post_call_analysis (Span)
├── llm_evaluation (Span)
└── Feedback Scores:
    ├── biomarker_coverage: 0.0-1.0
    ├── appointment_discussion: 0.0-1.0
    ├── conversation_completeness: 0.0-1.0
    ├── professional_tone: 0.0-1.0
    ├── call_outcome: 0.0-1.0
    └── overall_call_quality: 0.0-1.0
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'livekit'` | Run `pip install -r requirements.txt` in the activated venv. |
| `SIP call failed: no such host "my-voice-agent1 .pstn.twilio.com"` | Remove the stray space in your SIP trunk address in **LiveKit Console → SIP → Outbound Trunks** (e.g. `my-voice-agent1.pstn.twilio.com`). |
| `dispatch` prints nothing after running | Expected — dispatch is fire-and-forget. Make sure `python main.py start` is running in another terminal; the worker log and Opik trace show the outcome. Use `python main.py call ...` for a single-command flow. |
| The agent doesn't answer in `call` mode | The worker hadn't registered before the dispatch fired. Raise `--worker-wait` (e.g. `--worker-wait 15`). |
| `GROQ_API_KEY not set; cannot run LLM-as-judge evaluation` | Ensure `GROQ_API_KEY` is set in your `.env` file (the judge calls Groq directly inside `opik_integration.py`). |
| `worker is at full capacity, marking as unavailable` | Normal load-based scaling — the worker recovers automatically within a few seconds. |

## Configuration

### Customizing Patient Biomarkers

Edit `SAMPLE_PATIENT` in `config.py` or pass custom biomarkers via dispatch metadata:

```json
{
  "name": "John Doe",
  "phone_number": "+1234567890",
  "patient_id": "PT-001",
  "biomarkers": {
    "Blood Glucose": {
      "value": 142,
      "unit": "mg/dL",
      "reference_range": "70-100 mg/dL",
      "status": "HIGH"
    },
    "HbA1c": {
      "value": 7.8,
      "unit": "%",
      "reference_range": "<5.7%",
      "status": "HIGH"
    }
  }
}
```

### Adding New Evaluation Metrics

Add metrics in `opik_integration.py` → `evaluate_call_quality()`:

```python
def evaluate_call_quality(self, trace_id, transcript, analysis):
    results = []
    # ... existing metrics ...

    # Custom metric
    results.append(EvaluationResult(
        metric_name="my_custom_metric",
        score=0.85,
        reason="Custom evaluation logic",
        passed=True,
    ))
    return results
```

## File Reference

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point — commands: `dev`, `start`, `call`, `dispatch`, `analyze` |
| `agent.py` | LiveKit HealthcareAgent, `@function_tool`, shared call flow (`_run_call`) |
| `ai_gateway.py` | Standalone AI Gateway — rate limit, throttle, circuit breaker, retry, guardrails |
| `gateway_llm.py` | LiveKit bridge: `GatewayLLM(groq.LLM)` routing LLM calls through the gateway |
| `config.py` | Environment variables, `PatientInfo` data model, `SAMPLE_PATIENT` |
| `opik_integration.py` | Standalone Opik module — tracing, logging, rule-based + LLM-as-judge evaluation |
| `post_call_analysis.py` | Transcript analysis and call-outcome determination |
| `demo.py` | Sample transcript/tool-call data used by `python main.py analyze` |
| `requirements.txt` | Dependencies: `livekit-agents`, `livekit-plugins-groq`, `opik`, `python-dotenv` |
| `.env.example` | Environment variable reference template |
