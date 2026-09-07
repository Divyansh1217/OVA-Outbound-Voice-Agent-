"""Healthcare voice agent with biomarker discussion and appointment scheduling."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from livekit import agents, api
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    function_tool,
)
from livekit.plugins import deepgram, silero

from ai_gateway import GatewayConfig
from config import PatientInfo, load_config
from gateway_llm import GatewayLLM
from opik_integration import (
    ConversationTurn,
    OpikIntegration,
    PostCallAnalysis,
    ToolCallRecord,
)
from post_call_analysis import analyze_call

logger = logging.getLogger(__name__)


def build_gateway_llm(
    config: dict[str, Any],
    opik: OpikIntegration | None,
    trace_id: str,
) -> GatewayLLM:
    """Build the GatewayLLM that routes Groq calls through the AI Gateway.

    Fail fast with a clear message if the Groq API key is missing.
    """
    api_key = config["groq_api_key"] or None
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to .env to run the agent "
            "(the LLM is routed through the AI Gateway with rate limits and guardrails)."
        )
    llm = GatewayLLM(
        model="openai/gpt-oss-120b",
        api_key=api_key,
        gateway_config=GatewayConfig(),
        opik_client=opik._client if opik and opik._client else None,
        opik_project=config["opik_project"],
    )
    llm.set_trace_id(trace_id)
    return llm


# ---------------------------------------------------------------------------
# Appointment booking tool
# ---------------------------------------------------------------------------

def _simulate_booking(patient_name: str, doctor: str, preferred_time: str) -> dict[str, Any]:
    """Simulate booking a doctor consultation appointment.

    In production this would call a real scheduling API.
    """
    appointment_id = f"APT-{uuid.uuid4().hex[:8].upper()}"
    appointment_date = datetime.now(timezone.utc) + timedelta(days=3)
    return {
        "status": "confirmed",
        "appointment_id": appointment_id,
        "patient_name": patient_name,
        "doctor": doctor,
        "scheduled_date": appointment_date.strftime("%Y-%m-%d"),
        "scheduled_time": preferred_time,
        "location": "HealthCare Plus Clinic, 456 Medical Ave",
        "notes": "Bring latest lab results and insurance card",
    }


# ---------------------------------------------------------------------------
# Healthcare Agent
# ---------------------------------------------------------------------------

class HealthcareAgent(Agent):
    """AI voice agent for outbound healthcare calls.

    Calls patients to discuss health biomarkers and schedule doctor consultations.
    """

    def __init__(
        self,
        patient: PatientInfo,
        opik: OpikIntegration | None = None,
        trace_id: str = "",
        llm: Any = None,
    ):
        self.patient = patient
        self.opik = opik
        self.trace_id = trace_id
        self._llm = llm
        self.transcript: list[ConversationTurn] = []
        self.tool_calls: list[ToolCallRecord] = []
        self.call_start_time: datetime = datetime.now(timezone.utc)

        biomarker_text = patient.biomarker_summary()

        instructions = f"""You are a friendly and professional healthcare outreach agent calling a patient.

PATIENT INFORMATION:
- Name: {patient.name}
- Patient ID: {patient.patient_id}

HEALTH BIOMARKERS TO DISCUSS:
{biomarker_text}

YOUR TASK:
1. Greet the patient warmly and introduce yourself as calling from HealthCare Plus.
2. Inform the patient about their recent health metrics. For any values that are outside
   the normal range, explain what this means in simple, non-alarming language.
3. Recommend that they schedule a follow-up consultation with their doctor to discuss
   the results in detail.
4. Use the book_appointment tool to schedule the consultation if the patient agrees.
5. Be empathetic, clear, and professional. Use simple language the patient can understand.

IMPORTANT GUIDELINES:
- Do NOT diagnose or provide medical advice beyond what the biomarker values indicate.
- Always recommend consulting with their doctor for detailed medical guidance.
- If the patient asks questions you cannot answer, recommend they discuss with their doctor.
- Keep the conversation warm and supportive.
- If the patient wants to end the call, respect their wishes politely."""

        super().__init__(instructions=instructions, llm=llm)

    async def on_enter(self) -> None:
        """Called when the agent enters the session - initiates the conversation."""
        biomarker_text = self.patient.biomarker_summary()
        greeting = (
            f"Start the call by greeting {self.patient.name}, introducing yourself "
            f"as calling from HealthCare Plus regarding their recent health checkup results. "
            f"Then proceed to discuss their biomarkers one by one, starting with the most "
            f"concerning values."
        )
        self.session.generate_reply(instructions=greeting)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @function_tool
    async def book_appointment(
        self,
        context: RunContext,
        patient_name: str,
        preferred_time: str = "morning",
    ) -> dict[str, Any]:
        """Book a doctor consultation appointment for the patient.

        Use this tool when the patient agrees to schedule a follow-up consultation.
        The appointment will be booked with Dr. Rebecca Chen at HealthCare Plus Clinic.

        Args:
            patient_name: The full name of the patient
            preferred_time: Preferred time of day - morning, afternoon, or evening
        """
        result = _simulate_booking(
            patient_name=patient_name,
            doctor="Dr. Rebecca Chen",
            preferred_time=preferred_time,
        )

        # Log tool call
        record = ToolCallRecord(
            tool_name="book_appointment",
            arguments={"patient_name": patient_name, "preferred_time": preferred_time},
            result=result,
        )
        self.tool_calls.append(record)

        # Log to Opik
        if self.opik and self.trace_id:
            self.opik.log_tool_call(
                self.trace_id,
                "book_appointment",
                record.arguments,
                record.result,
            )

        logger.info("Appointment booked: %s", json.dumps(result, indent=2))
        return result

    # ------------------------------------------------------------------
    # Conversation tracking
    # ------------------------------------------------------------------

    def _track_conversation(self, session: Any) -> None:
        """Set up event listeners to capture the conversation transcript.

        The session must be the AgentSession driving this call, since the
        framework binds agent.session only after the session starts.
        """
        @session.on("user_input_transcribed")
        def on_user_input(event: Any) -> None:
            if event.is_final:
                turn = ConversationTurn(role="user", content=event.transcript)
                self.transcript.append(turn)
                if self.opik and self.trace_id:
                    self.opik.log_conversation_item(
                        self.trace_id, "user", event.transcript
                    )

        @session.on("conversation_item_added")
        def on_conversation_item(event: Any) -> None:
            from livekit.agents.llm import ChatMessage

            if isinstance(event.item, ChatMessage) and event.item.role == "assistant":
                content = event.item.text_content or ""
                if content:
                    # Output guardrail: check and redact if needed
                    if self._llm and hasattr(self._llm, "check_output_guardrail"):
                        content = self._llm.check_output_guardrail(content)
                    turn = ConversationTurn(role="assistant", content=content)
                    self.transcript.append(turn)
                    if self.opik and self.trace_id:
                        self.opik.log_conversation_item(
                            self.trace_id, "assistant", content
                        )

    # ------------------------------------------------------------------
    # Post-call analysis
    # ------------------------------------------------------------------

    def get_post_call_analysis(self) -> PostCallAnalysis:
        """Generate post-call analysis from collected data."""
        duration = (datetime.now(timezone.utc) - self.call_start_time).total_seconds()
        return analyze_call(
            transcript=self.transcript,
            tool_calls=self.tool_calls,
            call_duration=duration,
        )


def _make_session(llm: GatewayLLM) -> AgentSession:
    return AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-2-phonecall"),
        llm=llm,
        tts=deepgram.TTS(model="aura-2-thalia-en"),
    )


def _log_results(opik: OpikIntegration, trace_id: str, agent: HealthcareAgent) -> None:
    """Log post-call analysis, transcript, and evaluations for a finished call."""
    analysis = agent.get_post_call_analysis()
    opik.log_post_call_analysis(trace_id, analysis)
    if agent.transcript:
        opik.log_full_transcript(trace_id, agent.transcript)
        opik.run_evaluation(trace_id, agent.transcript, analysis)
        opik.run_llm_evaluation(trace_id, agent.transcript, analysis)
    opik.flush()
    logger.info("Call completed. Analysis: %s", analysis.summary)


async def _run_call(
    ctx: JobContext,
    config: dict[str, Any],
    patient: PatientInfo,
    mode: str,
    dial_sip: bool,
) -> None:
    """Start the session, optionally dial the patient via SIP, and log the call."""
    opik = OpikIntegration(
        project_name=config["opik_project"],
        api_key=config["opik_api_key"] or None,
        workspace=config["opik_workspace"] or None,
        host=config["opik_url"] or None,
    )
    opik.initialize()
    trace_id = opik.create_call_trace(patient, {"mode": mode})
    opik.log_audio_reference(
        trace_id,
        ctx.room.name,
        config.get("call_recording_url") or None,
    )

    llm = build_gateway_llm(config, opik, trace_id)
    agent = HealthcareAgent(patient=patient, opik=opik, trace_id=trace_id, llm=llm)
    session = _make_session(llm)
    agent._track_conversation(session)

    session_task = asyncio.create_task(session.start(agent=agent, room=ctx.room))

    if dial_sip:
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=config["sip_outbound_trunk_id"],
                    sip_call_to=patient.phone_number,
                    participant_identity=patient.phone_number,
                    wait_until_answered=True,
                )
            )
        except Exception as e:
            status = getattr(e, "sip_status_code", None) or getattr(e, "code", "unknown")
            detail = getattr(e, "sip_status", None) or getattr(e, "message", str(e))
            logger.error("SIP call failed (%s): %s", status, detail)
            session_task.cancel()
            try:
                opik.log_post_call_analysis(
                    trace_id,
                    PostCallAnalysis(
                        call_outcome="error",
                        summary=f"SIP call failed: {status} {detail}",
                    ),
                )
                opik.flush()
            except Exception:
                logger.exception("Failed to log SIP error to Opik")
            ctx.shutdown()
            return

    await session_task
    _log_results(opik, trace_id, agent)


async def outbound_caller(ctx: JobContext) -> None:
    """Outbound caller agent - dials out via SIP."""
    await ctx.connect()
    config = load_config()

    try:
        metadata = json.loads(ctx.job.metadata) if ctx.job.metadata else {}
    except json.JSONDecodeError:
        logger.error("Invalid job metadata JSON")
        ctx.shutdown()
        return

    patient = PatientInfo(
        name=metadata.get("name", "Unknown Patient"),
        phone_number=metadata.get("phone_number", ""),
        patient_id=metadata.get("patient_id", ""),
        biomarkers=metadata.get("biomarkers", {}),
    )

    if not patient.phone_number:
        logger.error("No phone number provided in metadata")
        ctx.shutdown()
        return

    await _run_call(ctx, config, patient, "outbound_sip", dial_sip=True)


async def local_test(ctx: JobContext) -> None:
    """Local test agent - no SIP dialing, starts conversation on join."""
    from config import SAMPLE_PATIENT

    await ctx.connect()
    await _run_call(ctx, load_config(), SAMPLE_PATIENT, "local_test", dial_sip=False)


def prewarm(proc: agents.JobProcess) -> None:
    """Prewarm models for faster cold starts."""
    proc.userdata["vad"] = silero.VAD.load()
