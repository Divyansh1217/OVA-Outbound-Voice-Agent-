"""Standalone Opik integration module for healthcare voice agent.

This module provides a self-contained interface to log call data, transcripts,
tool calls, and post-call analysis to Opik. It also implements online evaluation
scoring for completed calls.

Usage:
    from opik_integration import OpikIntegration

    opik = OpikIntegration(project_name="healthcare-voice-agent")
    opik.initialize()

    # During the call
    trace_id = opik.create_call_trace(patient_info, call_metadata)
    opik.log_conversation_item(trace_id, role="user", content="Hello")
    opik.log_tool_call(trace_id, "book_appointment", args, result)

    # After the call
    opik.log_post_call_analysis(trace_id, analysis)
    opik.run_evaluation(trace_id)
    opik.flush()
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import opik
from opik import Opik

logger = logging.getLogger(__name__)

LLM_JUDGE_DEFAULT_MODEL = "openai/gpt-oss-120b"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: str = ""
    is_final: bool = True

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class PostCallAnalysis:
    call_outcome: str  # "completed", "no_answer", "busy", "declined", "error"
    appointment_booked: bool = False
    appointment_details: dict[str, Any] = field(default_factory=dict)
    patient_agreed_not_booked: bool = False
    key_topics_discussed: list[str] = field(default_factory=list)
    sentiment: str = "neutral"
    duration_seconds: float = 0.0
    summary: str = ""


@dataclass
class EvaluationResult:
    metric_name: str
    score: float  # 0.0 to 1.0
    reason: str = ""
    passed: bool = True


# ---------------------------------------------------------------------------
# Main integration class
# ---------------------------------------------------------------------------

class OpikIntegration:
    """Standalone Opik integration for healthcare voice agent calls."""

    def __init__(
        self,
        project_name: str = "healthcare-voice-agent",
        api_key: str | None = None,
        workspace: str | None = None,
        host: str | None = None,
    ):
        self.project_name = project_name
        self._api_key = api_key
        self._workspace = workspace
        self._host = host
        self._client: Opik | None = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Initialize the Opik client."""
        if self._initialized:
            return

        kwargs: dict[str, Any] = {"project_name": self.project_name}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._workspace:
            kwargs["workspace"] = self._workspace
        if self._host:
            kwargs["host"] = self._host

        self._client = Opik(**kwargs)
        self._initialized = True
        logger.info("Opik client initialized for project: %s", self.project_name)

    def _ensure_client(self) -> Opik:
        if not self._initialized:
            self.initialize()
        assert self._client is not None
        return self._client

    def flush(self) -> None:
        """Flush pending traces to Opik."""
        if self._client:
            self._client.flush()
            logger.info("Opik traces flushed.")

    # ------------------------------------------------------------------
    # Trace creation
    # ------------------------------------------------------------------

    def create_call_trace(
        self,
        patient_info: Any,
        call_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a top-level trace for an outbound call.

        Returns the trace ID for subsequent logging calls.
        """
        client = self._ensure_client()
        # Opik requires version-7 UUIDs for trace/thread IDs
        from opik.id_helpers import generate_id

        trace_id = generate_id()
        metadata = {
            "call_type": "outbound_healthcare",
            "patient_name": getattr(patient_info, "name", "unknown"),
            "patient_id": getattr(patient_info, "patient_id", ""),
            "phone_number": getattr(patient_info, "phone_number", ""),
            "initiated_at": datetime.now(timezone.utc).isoformat(),
            **(call_metadata or {}),
        }

        # Build biomarker summary for input
        biomarkers = getattr(patient_info, "biomarkers", {})
        input_data = {
            "patient_name": getattr(patient_info, "name", "unknown"),
            "patient_id": getattr(patient_info, "patient_id", ""),
            "biomarkers": biomarkers,
            "call_purpose": "health_metrics_review_and_appointment_scheduling",
        }

        client.trace(
            id=trace_id,
            name="outbound_healthcare_call",
            input=input_data,
            output=None,
            metadata=metadata,
            tags=["outbound", "healthcare", "voice-agent"],
            thread_id=trace_id,
        )
        logger.info("Created Opik trace: %s", trace_id)
        return trace_id

    # ------------------------------------------------------------------
    # Conversation logging
    # ------------------------------------------------------------------

    def log_conversation_item(
        self,
        trace_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a single conversation turn to the trace."""
        client = self._ensure_client()
        span_name = f"conversation_{role}"
        input_data = {"role": role, "content": content}
        output_data = {"logged": True}

        client.span(
            trace_id=trace_id,
            name=span_name,
            type="general",
            input=input_data,
            output=output_data,
            metadata=metadata or {},
        )

    def log_full_transcript(
        self,
        trace_id: str,
        turns: list[ConversationTurn],
    ) -> None:
        """Log the complete conversation transcript as a single span."""
        client = self._ensure_client()
        transcript_data = [
            {"role": t.role, "content": t.content, "timestamp": t.timestamp}
            for t in turns
        ]
        client.span(
            trace_id=trace_id,
            name="full_transcript",
            type="general",
            input={"total_turns": len(turns)},
            output={"transcript": transcript_data},
            metadata={"turn_count": len(turns)},
        )

    # ------------------------------------------------------------------
    # Tool call logging
    # ------------------------------------------------------------------

    def log_tool_call(
        self,
        trace_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a function/tool call to the trace."""
        client = self._ensure_client()
        client.span(
            trace_id=trace_id,
            name=f"tool_call_{tool_name}",
            type="tool",
            input={"tool": tool_name, "arguments": arguments},
            output={"result": result},
            metadata=metadata or {},
        )

    def log_audio_reference(
        self,
        trace_id: str,
        room_name: str,
        recording_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a reference to the call audio/recording.

        ``recording_url`` is an optional LiveKit Egress / hosted recording URL;
        the LiveKit room name is always captured so audio can be located even
        when no recording has been configured.
        """
        client = self._ensure_client()
        output_data: dict[str, Any] = {"room_name": room_name}
        if recording_url:
            output_data["recording_url"] = recording_url
        client.span(
            trace_id=trace_id,
            name="audio_reference",
            type="general",
            input={"request": "call_audio_reference"},
            output=output_data,
            metadata={"recording_configured": bool(recording_url), **(metadata or {})},
        )

    # ------------------------------------------------------------------
    # Post-call analysis
    # ------------------------------------------------------------------

    def log_post_call_analysis(
        self,
        trace_id: str,
        analysis: PostCallAnalysis,
    ) -> None:
        """Log the post-call analysis and update the trace output."""
        client = self._ensure_client()
        analysis_data = {
            "call_outcome": analysis.call_outcome,
            "appointment_booked": analysis.appointment_booked,
            "appointment_details": analysis.appointment_details,
            "patient_agreed_not_booked": analysis.patient_agreed_not_booked,
            "key_topics_discussed": analysis.key_topics_discussed,
            "sentiment": analysis.sentiment,
            "duration_seconds": analysis.duration_seconds,
            "summary": analysis.summary,
        }
        client.span(
            trace_id=trace_id,
            name="post_call_analysis",
            type="general",
            input={"analysis_request": True},
            output=analysis_data,
            metadata={"analysis_version": "1.0"},
        )
        logger.info("Logged post-call analysis for trace %s", trace_id)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_call_quality(
        self,
        trace_id: str,
        transcript: list[ConversationTurn],
        analysis: PostCallAnalysis,
    ) -> list[EvaluationResult]:
        """Run rule-based evaluation metrics on the completed call.

        These simulate what Opik online evaluation rules would do.
        Returns a list of evaluation results that are logged as feedback scores.
        """
        results: list[EvaluationResult] = []

        # Metric 1: Biomarker Coverage - did the agent discuss the biomarkers?
        biomarker_mentioned = any(
            any(
                kw in turn.content.lower()
                for kw in ["glucose", "hba1c", "cholesterol", "blood pressure", "blood sugar"]
            )
            for turn in transcript
            if turn.role == "assistant"
        )
        results.append(
            EvaluationResult(
                metric_name="biomarker_coverage",
                score=1.0 if biomarker_mentioned else 0.0,
                reason="Agent discussed health biomarkers with the patient"
                if biomarker_mentioned
                else "Agent did not discuss any health biomarkers",
                passed=biomarker_mentioned,
            )
        )

        # Metric 2: Appointment Discussion - did the agent attempt scheduling?
        appointment_discussed = any(
            any(
                kw in turn.content.lower()
                for kw in ["appointment", "schedule", "consultation", "doctor", "visit"]
            )
            for turn in transcript
            if turn.role == "assistant"
        )
        results.append(
            EvaluationResult(
                metric_name="appointment_discussion",
                score=1.0 if appointment_discussed else 0.0,
                reason="Agent discussed appointment scheduling"
                if appointment_discussed
                else "Agent did not discuss appointment scheduling",
                passed=appointment_discussed,
            )
        )

        # Metric 3: Conversation Completeness - minimum turns exchanged
        user_turns = [t for t in transcript if t.role == "user"]
        min_turns = 3
        completeness = min(1.0, len(user_turns) / min_turns)
        results.append(
            EvaluationResult(
                metric_name="conversation_completeness",
                score=completeness,
                reason=f"Patient responded {len(user_turns)} times (minimum {min_turns})",
                passed=completeness >= 0.5,
            )
        )

        # Metric 4: Professional Tone - no negative indicators
        negative_indicators = ["rude", "angry", "unprofessional", "inappropriate"]
        has_negative = any(
            indicator in turn.content.lower()
            for turn in transcript
            if turn.role == "assistant"
            for indicator in negative_indicators
        )
        tone_score = 0.0 if has_negative else 1.0
        results.append(
            EvaluationResult(
                metric_name="professional_tone",
                score=tone_score,
                reason="Maintained professional tone throughout"
                if not has_negative
                else "Detected unprofessional language",
                passed=not has_negative,
            )
        )

        # Metric 5: Call Outcome Appropriateness
        outcome_score = 1.0 if analysis.call_outcome in ("completed", "no_answer") else 0.5
        results.append(
            EvaluationResult(
                metric_name="call_outcome",
                score=outcome_score,
                reason=f"Call outcome: {analysis.call_outcome}",
                passed=outcome_score >= 0.5,
            )
        )

        # Metric 6: Booking Follow-Through - if the patient agreed to book,
        # the appointment must actually be confirmed.
        if analysis.appointment_booked:
            booking_score, booking_reason = 1.0, "Appointment successfully booked"
            booking_passed = True
        elif analysis.patient_agreed_not_booked:
            booking_score, booking_reason = 0.0, (
                "Patient agreed to an appointment but the booking tool was never "
                "invoked - missed confirmation"
            )
            booking_passed = False
        else:
            booking_score, booking_reason = 1.0, "No booking expected (patient did not agree)"
            booking_passed = True
        results.append(
            EvaluationResult(
                metric_name="booking_follow_through",
                score=booking_score,
                reason=booking_reason,
                passed=booking_passed,
            )
        )

        return results

    def run_evaluation(
        self,
        trace_id: str,
        transcript: list[ConversationTurn],
        analysis: PostCallAnalysis,
    ) -> list[EvaluationResult]:
        """Run evaluations and log results as feedback scores to the trace."""
        client = self._ensure_client()
        eval_results = self.evaluate_call_quality(trace_id, transcript, analysis)

        for result in eval_results:
            client.log_traces_feedback_scores(
                scores=[
                    {
                        "id": trace_id,
                        "name": result.metric_name,
                        "value": result.score,
                        "reason": result.reason,
                        "project_name": self.project_name,
                    }
                ]
            )
            logger.info(
                "Evaluation '%s': score=%.2f passed=%s reason=%s",
                result.metric_name,
                result.score,
                result.passed,
                result.reason,
            )

        logger.info(
            "Completed %d evaluations for trace %s", len(eval_results), trace_id
        )
        return eval_results

    # ------------------------------------------------------------------
    # LLM-as-judge evaluation (online evaluation)
    # ------------------------------------------------------------------

    def run_llm_evaluation(
        self,
        trace_id: str,
        transcript: list[ConversationTurn],
        analysis: PostCallAnalysis,
        judge: Any = None,
        judge_model: str | None = None,
    ) -> EvaluationResult:
        """Run a genuine LLM-as-judge evaluation of the completed call.

        Calls Groq (using GROQ_API_KEY / GROQ_MODEL from the environment) to
        score the call 0.0-1.0. A custom ``judge`` callable ``judge(prompt: str) -> str``
        may be injected instead to keep the module standalone and pluggable. The
        model response, parsed score, and reason are logged as an ``llm`` span plus
        a feedback score on the trace (i.e. an online evaluation for production
        calls).
        """
        client = self._ensure_client()

        transcript_text = "\n".join(
            f"{t.role.upper()}: {t.content}" for t in transcript
        )
        eval_prompt = f"""You are an expert evaluator for healthcare AI voice agents.
Evaluate the following call transcript and analysis.

TRANSCRIPT:
{transcript_text}

ANALYSIS:
- Outcome: {analysis.call_outcome}
- Appointment booked: {analysis.appointment_booked}
- Patient agreed but booking not confirmed: {analysis.patient_agreed_not_booked}
- Sentiment: {analysis.sentiment}
- Summary: {analysis.summary}

Rate this call on a scale of 0.0 to 1.0 considering:
1. Was the health information communicated clearly and accurately?
2. Was the tone appropriate for a healthcare context?
3. Was the agent helpful in scheduling follow-up care?
4. Did the conversation flow naturally?
5. Did the agent follow through on booking an appointment when the patient agreed?

Reply with exactly two lines:
SCORE: <a single number between 0.0 and 1.0>
REASON: <one short sentence>"""

        model = judge_model or os.getenv("GROQ_MODEL", LLM_JUDGE_DEFAULT_MODEL)
        raw = ""
        error: str | None = None
        try:
            raw = judge(eval_prompt) if judge is not None else self._call_groq_judge(eval_prompt, model)
        except Exception as e:
            error = f"{e.__class__.__name__}: {e}"
            logger.warning("LLM-as-judge call failed: %s", error)

        score, reason = self._parse_judge_response(raw)
        if error:
            score, reason, passed = 0.0, error, False
        else:
            passed = score >= 0.5

        result = EvaluationResult(
            metric_name="overall_call_quality",
            score=score,
            reason=reason,
            passed=passed,
        )

        try:
            client.span(
                trace_id=trace_id,
                name="llm_evaluation",
                type="llm",
                input={"eval_prompt": eval_prompt},
                output={"content": raw or error or "", "score": result.score, "reason": result.reason},
                metadata={
                    "model": model,
                    "evaluation_type": "llm_as_judge",
                    "online": True,
                    "evaluation_criteria": [
                        "health_info_clarity",
                        "tone_appropriateness",
                        "scheduling_helpfulness",
                        "conversation_flow",
                        "booking_follow_through",
                    ],
                },
            )
        except Exception:
            logger.exception("Failed to log LLM evaluation span")

        try:
            client.log_traces_feedback_scores(
                scores=[
                    {
                        "id": trace_id,
                        "name": result.metric_name,
                        "value": result.score,
                        "reason": result.reason,
                        "project_name": self.project_name,
                    }
                ]
            )
        except Exception:
            logger.exception("Failed to log evaluation score")

        logger.info(
            "LLM-as-judge '%s': score=%.2f passed=%s reason=%s",
            result.metric_name, result.score, result.passed, result.reason,
        )
        return result

    def _call_groq_judge(self, prompt: str, model: str) -> str:
        """Call Groq synchronously with the judge prompt."""
        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set; cannot run LLM-as-judge evaluation")
        response = Groq(api_key=api_key).chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_judge_response(raw: str) -> tuple[float, str]:
        """Parse 'SCORE: x / REASON: y' from the judge output (robust fallbacks)."""
        if not raw:
            return 0.5, "No judge response"
        m = re.search(r"SCORE:\s*(-?[0-9]+(?:\.[0-9]+)?)", raw, re.IGNORECASE)
        if m:
            score = float(m.group(1))
        else:
            m2 = re.search(r"([0-9]+(?:\.[0-9]+)?)", raw)
            score = float(m2.group(1)) if m2 else 0.5
        m3 = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE | re.DOTALL)
        reason = m3.group(1).strip() if m3 else raw.strip()[:200]
        return min(1.0, max(0.0, score)), reason
