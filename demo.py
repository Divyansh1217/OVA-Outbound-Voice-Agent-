"""Sample data used by `python main.py analyze`."""

from opik_integration import ConversationTurn, ToolCallRecord

SAMPLE_BOOKING_ARGS = {"patient_name": "Sarah Johnson", "preferred_time": "morning"}

SAMPLE_BOOKING_RESULT = {
    "status": "confirmed",
    "appointment_id": "APT-A1B2C3D4",
    "patient_name": "Sarah Johnson",
    "doctor": "Dr. Rebecca Chen",
    "scheduled_date": "2026-09-10",
    "scheduled_time": "morning",
    "location": "HealthCare Plus Clinic, 456 Medical Ave",
    "notes": "Bring latest lab results and insurance card",
}

SAMPLE_TRANSCRIPT: list[ConversationTurn] = [
    ConversationTurn(role="assistant", content="Good morning! This is Dr. AI calling from HealthCare Plus. Am I speaking with Sarah Johnson?"),
    ConversationTurn(role="user", content="Yes, this is Sarah. Who is calling?"),
    ConversationTurn(role="assistant", content="Hi Sarah, I'm calling from HealthCare Plus to review your recent lab results. I see your fasting blood glucose was 142 mg/dL, which is above the normal range of 70-100. Your HbA1c was 7.8%, also above the normal range. These results suggest your blood sugar levels have been running high."),
    ConversationTurn(role="user", content="Oh, that sounds concerning. What does that mean?"),
    ConversationTurn(role="assistant", content="It means we'd recommend a follow-up consultation with Dr. Rebecca Chen to discuss your results and create a care plan. She can help with managing these levels through lifestyle changes or medication if needed."),
    ConversationTurn(role="user", content="Okay, that makes sense. Can you schedule that for me?"),
    ConversationTurn(role="assistant", content="Absolutely! Let me book that appointment for you right now."),
    ConversationTurn(role="user", content="Thank you, I appreciate it."),
    ConversationTurn(role="assistant", content="Your appointment has been confirmed! You're scheduled with Dr. Rebecca Chen in 3 days at the HealthCare Plus Clinic. Please bring your latest lab results and insurance card. Is there anything else I can help you with?"),
    ConversationTurn(role="user", content="No, that's all. Thank you so much!"),
    ConversationTurn(role="assistant", content="You're welcome, Sarah! Take care, and we'll see you at your appointment. Goodbye!"),
]

SAMPLE_TOOL_CALL = ToolCallRecord(
    tool_name="book_appointment",
    arguments=SAMPLE_BOOKING_ARGS,
    result=SAMPLE_BOOKING_RESULT,
)