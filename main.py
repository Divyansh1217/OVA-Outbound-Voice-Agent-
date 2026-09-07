"""Entry point for the healthcare voice agent.

Usage:
    # Local test mode (no SIP, for development):
    python main.py dev

    # Production outbound calling (requires SIP trunk):
    python main.py start

    # Dispatch an outbound call:
    python main.py dispatch --phone +1234567890 --name "Sarah Johnson"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_dev() -> None:
    """Run in local development mode."""
    from agent import local_test, prewarm
    from livekit.agents import WorkerOptions, cli

    logger.info("Starting in local dev mode...")
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=local_test,
            prewarm_fnc=prewarm,
            agent_name="healthcare-test",
        )
    )


def run_start() -> None:
    """Run in production outbound calling mode."""
    from agent import outbound_caller, prewarm
    from livekit.agents import WorkerOptions, cli

    logger.info("Starting in production outbound mode...")
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=outbound_caller,
            prewarm_fnc=prewarm,
            agent_name="healthcare-caller",
        )
    )


def run_dispatch(args: argparse.Namespace) -> None:
    """Dispatch an outbound call via LiveKit API."""
    from config import SAMPLE_PATIENT, load_config

    config = load_config()

    # Build patient metadata
    patient_name = args.name or SAMPLE_PATIENT.name
    patient_id = args.patient_id or SAMPLE_PATIENT.patient_id
    phone_number = args.phone or SAMPLE_PATIENT.phone_number
    biomarkers = SAMPLE_PATIENT.biomarkers if not args.biomarkers else json.loads(args.biomarkers)

    metadata = json.dumps({
        "name": patient_name,
        "phone_number": phone_number,
        "patient_id": patient_id,
        "biomarkers": biomarkers,
    })

    logger.info("Dispatching call to %s (%s)", patient_name, phone_number)
    logger.info("Metadata: %s", metadata)

    # LiveKit dispatch
    from livekit import api

    async def _dispatch():
        async with api.LiveKitAPI(
            url=config["livekit_url"],
            api_key=config["livekit_api_key"],
            api_secret=config["livekit_api_secret"],
        ) as lkapi:
            room_name = f"healthcare-call-{patient_id}-{int(asyncio.get_event_loop().time())}"
            await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name="healthcare-caller",
                    room=room_name,
                    metadata=metadata,
                )
            )
            logger.info("Dispatched call. Room: %s", room_name)

    asyncio.run(_dispatch())


def run_analyze() -> None:
    """Run post-call analysis and Opik logging on the sample call."""
    import demo
    from config import SAMPLE_PATIENT, load_config
    from opik_integration import OpikIntegration
    from post_call_analysis import analyze_call

    config = load_config()

    opik = OpikIntegration(
        project_name=config["opik_project"],
        api_key=config["opik_api_key"] or None,
        workspace=config["opik_workspace"] or None,
        host=config["opik_url"] or None,
    )
    opik.initialize()

    trace_id = opik.create_call_trace(SAMPLE_PATIENT, {"mode": "manual_analysis"})
    opik.log_audio_reference(trace_id, "demo-room")

    for turn in demo.SAMPLE_TRANSCRIPT:
        opik.log_conversation_item(trace_id, turn.role, turn.content)
    opik.log_full_transcript(trace_id, demo.SAMPLE_TRANSCRIPT)
    opik.log_tool_call(
        trace_id,
        demo.SAMPLE_TOOL_CALL.tool_name,
        demo.SAMPLE_TOOL_CALL.arguments,
        demo.SAMPLE_TOOL_CALL.result,
    )

    analysis = analyze_call(
        transcript=demo.SAMPLE_TRANSCRIPT,
        tool_calls=[demo.SAMPLE_TOOL_CALL],
        call_duration=185.0,
    )
    opik.log_post_call_analysis(trace_id, analysis)

    eval_results = opik.run_evaluation(trace_id, demo.SAMPLE_TRANSCRIPT, analysis)
    eval_results.append(opik.run_llm_evaluation(trace_id, demo.SAMPLE_TRANSCRIPT, analysis))

    opik.flush()

    # Print results
    print("\n" + "=" * 60)
    print("POST-CALL ANALYSIS")
    print("=" * 60)
    print(f"Outcome: {analysis.call_outcome}")
    print(f"Appointment Booked: {analysis.appointment_booked}")
    print(f"Topics Discussed: {', '.join(analysis.key_topics_discussed)}")
    print(f"Sentiment: {analysis.sentiment}")
    print(f"Summary: {analysis.summary}")
    print(f"\nOpik Trace ID: {trace_id}")
    print(f"Opik Project: {config['opik_project']}")
    print("\nEVALUATION RESULTS:")
    for er in eval_results:
        status = "PASS" if er.passed else "FAIL"
        print(f"  [{status}] {er.metric_name}: {er.score:.2f} - {er.reason}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Healthcare Voice Agent")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("dev", help="Run in local dev mode")
    subparsers.add_parser("start", help="Run in production outbound mode")

    dispatch_parser = subparsers.add_parser("dispatch", help="Dispatch an outbound call")
    dispatch_parser.add_argument("--phone", help="Phone number to call")
    dispatch_parser.add_argument("--name", help="Patient name")
    dispatch_parser.add_argument("--patient-id", help="Patient ID")
    dispatch_parser.add_argument("--biomarkers", help="JSON string of biomarker data")

    analyze_parser = subparsers.add_parser("analyze", help="Run analysis on sample call")

    args = parser.parse_args()

    if args.command == "dev":
        run_dev()
    elif args.command == "start":
        run_start()
    elif args.command == "dispatch":
        run_dispatch(args)
    elif args.command == "analyze":
        run_analyze()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
