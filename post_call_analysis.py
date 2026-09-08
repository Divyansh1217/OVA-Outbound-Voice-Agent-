"""Post-call analysis module for healthcare voice agent."""

from __future__ import annotations

import logging
from typing import Any

from opik_integration import ConversationTurn, PostCallAnalysis, ToolCallRecord

logger = logging.getLogger(__name__)


def analyze_call(
    transcript: list[ConversationTurn],
    tool_calls: list[ToolCallRecord],
    call_duration: float = 0.0,
    call_disconnect_reason: str = "",
) -> PostCallAnalysis:
    """Analyze a completed call and produce a structured summary.

    Examines the transcript and tool call records to determine:
    - Whether the call completed successfully
    - Whether an appointment was booked
    - Key topics discussed
    - Overall sentiment
    - A human-readable summary
    """
    appointment_booked = False
    appointment_details: dict[str, Any] = {}
    patient_agreed_not_booked = False
    key_topics: list[str] = []
    sentiment = "neutral"

    # Check tool calls for appointment booking
    for tc in tool_calls:
        if tc.tool_name == "book_appointment":
            appointment_booked = tc.result.get("status") == "confirmed" if isinstance(tc.result, dict) else True
            if isinstance(tc.result, dict):
                appointment_details = tc.result
            elif isinstance(tc.result, str):
                appointment_details = {"confirmation": tc.result}

    # Cross-check the transcript: if the patient explicitly agreed to book but
    # the tool was never invoked, flag it as a missed booking.
    # This catches LLM failures where book_appointment was not called even
    # though the patient consented.
    if not appointment_booked:
        patient_turns = [t.content.lower() for t in transcript if t.role == "user"]
        agreement_words = [
            "yes", "yeah", "yep", "sure", "ok", "okay", "please", "please do",
            "go ahead", "book it", "book me", "schedule", "schedule me",
            "make an appointment", "i'd like", "i would like", "confirmed",
        ]
        booking_context_words = ["appointment", "book", "schedule", "consultation", "visit", "doctor"]
        for turn in patient_turns:
            mentions_context = any(w in turn for w in booking_context_words)
            agrees = any(w in turn for w in agreement_words)
            if mentions_context and agrees:
                patient_agreed_not_booked = True
                break

    # Analyze transcript for topics
    topic_keywords = {
        "blood glucose": ["glucose", "blood sugar", "fasting"],
        "hba1c": ["hba1c", "a1c", "hemoglobin"],
        "cholesterol": ["cholesterol", "lipid"],
        "blood pressure": ["blood pressure", "hypertension", "systolic", "diastolic"],
        "appointment scheduling": ["appointment", "schedule", "consultation", "visit"],
        "medication": ["medication", "medicine", "drug", "prescription"],
        "lifestyle": ["diet", "exercise", "weight", "lifestyle"],
    }

    full_text = " ".join(t.content.lower() for t in transcript)
    for topic, keywords in topic_keywords.items():
        if any(kw in full_text for kw in keywords):
            key_topics.append(topic)

    # Determine call outcome
    if call_disconnect_reason in ("no_answer", "busy", "declined"):
        call_outcome = call_disconnect_reason
    elif len(transcript) < 2:
        call_outcome = "no_answer"
    else:
        call_outcome = "completed"

    # Sentiment analysis (simple keyword-based)
    positive_words = ["thank", "great", "good", "happy", "appreciate", "wonderful", "helpful"]
    negative_words = ["angry", "frustrated", "annoyed", "upset", "terrible", "bad", "worst"]

    positive_count = sum(1 for w in positive_words if w in full_text)
    negative_count = sum(1 for w in negative_words if w in full_text)

    if positive_count > negative_count:
        sentiment = "positive"
    elif negative_count > positive_count:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    # Build summary
    patient_turns = [t for t in transcript if t.role == "user"]
    agent_turns = [t for t in transcript if t.role == "assistant"]

    summary_parts = [
        f"Outbound healthcare call with {len(patient_turns)} patient responses and {len(agent_turns)} agent messages.",
    ]

    if key_topics:
        summary_parts.append(f"Topics covered: {', '.join(key_topics)}.")

    if appointment_booked:
        summary_parts.append("Appointment was successfully booked.")
    elif patient_agreed_not_booked:
        summary_parts.append(
            "Patient agreed to book an appointment but no booking was confirmed "
            "(tool call missed) - review required."
        )
    else:
        summary_parts.append("No appointment was booked during this call.")

    summary_parts.append(f"Overall sentiment: {sentiment}.")

    return PostCallAnalysis(
        call_outcome=call_outcome,
        appointment_booked=appointment_booked,
        appointment_details=appointment_details,
        patient_agreed_not_booked=patient_agreed_not_booked,
        key_topics_discussed=key_topics,
        sentiment=sentiment,
        duration_seconds=call_duration,
        summary=" ".join(summary_parts),
    )
