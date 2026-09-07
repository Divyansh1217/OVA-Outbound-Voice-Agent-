"""Configuration and data models for the healthcare voice agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PatientInfo:
    """Patient information for the outbound call."""

    name: str
    phone_number: str
    biomarkers: dict[str, Any] = field(default_factory=dict)
    patient_id: str = ""

    def biomarker_summary(self) -> str:
        lines = []
        for key, val in self.biomarkers.items():
            if isinstance(val, dict):
                value = val.get("value", "N/A")
                unit = val.get("unit", "")
                ref = val.get("reference_range", "")
                status = val.get("status", "")
                line = f"- {key}: {value} {unit}"
                if ref:
                    line += f" (reference: {ref})"
                if status:
                    line += f" [{status}]"
                lines.append(line)
            else:
                lines.append(f"- {key}: {val}")
        return "\n".join(lines) if lines else "No biomarker data available."


def load_config() -> dict[str, str]:
    """Load configuration from environment variables (.env file is loaded automatically)."""
    from dotenv import load_dotenv

    load_dotenv()
    return {
        "livekit_url": os.getenv("LIVEKIT_URL", ""),
        "livekit_api_key": os.getenv("LIVEKIT_API_KEY", ""),
        "livekit_api_secret": os.getenv("LIVEKIT_API_SECRET", ""),
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "deepgram_api_key": os.getenv("DEEPGRAM_API_KEY", ""),
        "sip_outbound_trunk_id": os.getenv("SIP_OUTBOUND_TRUNK_ID", ""),
        "opik_api_key": os.getenv("OPIK_API_KEY", ""),
        "opik_workspace": os.getenv("OPIK_WORKSPACE", ""),
        "opik_url": os.getenv("OPIK_URL_OVERRIDE", ""),
        "opik_project": os.getenv("OPIK_PROJECT_NAME", "healthcare-voice-agent"),
        "call_recording_url": os.getenv("CALL_RECORDING_URL", ""),
    }


SAMPLE_PATIENT = PatientInfo(
    name="Sarah Johnson",
    phone_number="+1234567890",
    patient_id="PT-2024-0042",
    biomarkers={
        "Blood Glucose (Fasting)": {
            "value": 142,
            "unit": "mg/dL",
            "reference_range": "70-100 mg/dL",
            "status": "HIGH",
        },
        "HbA1c": {
            "value": 7.8,
            "unit": "%",
            "reference_range": "<5.7%",
            "status": "HIGH",
        },
        "Total Cholesterol": {
            "value": 218,
            "unit": "mg/dL",
            "reference_range": "<200 mg/dL",
            "status": "BORDERLINE HIGH",
        },
        "Blood Pressure (Systolic)": {
            "value": 138,
            "unit": "mmHg",
            "reference_range": "<120 mmHg",
            "status": "ELEVATED",
        },
    },
)
