"""Entry point for the healthcare voice agent.

Usage:
    # Local test mode (no SIP, for development):
    python main.py dev

    # Production outbound calling (requires SIP trunk):
    python main.py start

    # Dispatch an outbound call (worker must already be running with `start`):
    python main.py dispatch --phone +1234567890 --name "Sarah Johnson"

    # One-command outbound call - starts the worker, dispatches, and dials,
    # then exits when the call ends:
    python main.py call --phone +1234567890 --name "Sarah Johnson"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time

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


def build_patient_metadata(args: argparse.Namespace) -> tuple[dict[str, str], str]:
    """Build patient metadata dict and its JSON string from CLI args or sample patient."""
    from config import SAMPLE_PATIENT

    patient_name = args.name or SAMPLE_PATIENT.name
    patient_id = args.patient_id or SAMPLE_PATIENT.patient_id
    phone_number = args.phone or SAMPLE_PATIENT.phone_number
    biomarkers = SAMPLE_PATIENT.biomarkers if not args.biomarkers else json.loads(args.biomarkers)

    metadata = {
        "name": patient_name,
        "phone_number": phone_number,
        "patient_id": patient_id,
        "biomarkers": biomarkers,
    }
    return metadata, json.dumps(metadata)


def dispatch_call(room_name: str, metadata_json: str) -> None:
    """Create an agent dispatch via the LiveKit API."""
    from config import load_config
    from livekit import api

    config = load_config()

    async def _dispatch():
        async with api.LiveKitAPI(
            url=config["livekit_url"],
            api_key=config["livekit_api_key"],
            api_secret=config["livekit_api_secret"],
        ) as lkapi:
            await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name="healthcare-caller",
                    room=room_name,
                    metadata=metadata_json,
                )
            )
            logger.info("Dispatched call. Room: %s", room_name)

    asyncio.run(_dispatch())


def run_dispatch(args: argparse.Namespace) -> None:
    """Dispatch an outbound call via LiveKit API."""
    _, metadata_json = build_patient_metadata(args)
    logger.info("Dispatching call to %s (%s)", args.name or "Sarah Johnson", args.phone or "+1234567890")
    logger.info("Metadata: %s", metadata_json)
    dispatch_call(
        f"healthcare-call-{int(asyncio.get_event_loop().time())}",
        metadata_json,
    )


def run_call(args: argparse.Namespace) -> None:
    """Run the worker and dispatch+dial a single call, then exit when it ends.

    One-command alternative to running `python main.py start` and
    `python main.py dispatch` in separate terminals.
    """
    from agent import outbound_caller, prewarm
    from livekit.agents import WorkerOptions, cli

    if args.detach:
        # Detached mode: delegate to the two existing commands the way a
        # shell one-liner would (`start` in background, then `dispatch`).
        import subprocess

        worker = subprocess.Popen(
            [sys.executable, sys.argv[0], "start"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(args.worker_wait)
            run_dispatch(args)
            # Keep orchestrating until the worker exits.
            while worker.poll() is None:
                time.sleep(1)
        finally:
            worker.terminate()
            worker.wait(timeout=30)
        return

    # In-process mode: run the worker on a background thread.
    error_box: list[BaseException | None] = [None]

    def _run_worker() -> None:
        try:
            cli.run_app(
                WorkerOptions(
                    entrypoint_fnc=outbound_caller,
                    prewarm_fnc=prewarm,
                    agent_name="healthcare-caller",
                )
            )
        except BaseException as e:  # surface errors to the main thread
            error_box[0] = e

    worker_thread = threading.Thread(target=_run_worker, daemon=True)
    worker_thread.start()

    # Give LiveKit Cloud a moment to register the worker before dispatching.
    logger.info("Starting worker and waiting %ss before dispatch...", args.worker_wait)
    time.sleep(args.worker_wait)

    metadata, metadata_json = build_patient_metadata(args)
    room_name = f"healthcare-call-{metadata['patient_id']}-{int(time.time())}"
    logger.info("Dispatching call to %s (%s)", metadata["name"], metadata["phone_number"])
    dispatch_call(room_name, metadata_json)

    # Block until the worker's call finishes. The worker stays up so the room
    # lifecycle (connect, SIP dial, session, post-call logging) completes.
    while worker_thread.is_alive():
        if error_box[0] is not None:
            logger.error("Worker crashed: %s", error_box[0])
            sys.exit(1)
        time.sleep(0.5)

    if error_box[0] is not None:
        logger.error("Worker exited with error: %s", error_box[0])
        sys.exit(1)
    logger.info("Worker exited. Call flow complete.")


def run_analyze() -> None:
    """Run post-call analysis and Opik logging on the sample calls.

    Demonstrates both scenarios:
      1. Successful booking (tool call confirm)
      2. Patient agreed but tool was never invoked (missed booking detected via
         transcript cross-check)
    """
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

    scenarios = [
        (
            "CALL 1 - SUCCESSFUL BOOKING",
            SAMPLE_PATIENT,
            "demo-room",
            demo.SAMPLE_TRANSCRIPT,
            [demo.SAMPLE_TOOL_CALL],
            185.0,
        ),
        (
            "CALL 2 - MISSED BOOKING (patient agreed, tool missed)",
            SAMPLE_PATIENT,
            "demo-room-missed",
            demo.SAMPLE_MISSED_BOOKING_TRANSCRIPT,
            demo.SAMPLE_MISSED_BOOKING_TOOL_CALLS,
            160.0,
        ),
    ]

    for label, patient, room, transcript, tool_calls, duration in scenarios:
        trace_id = opik.create_call_trace(patient, {"mode": "manual_analysis"})
        opik.log_audio_reference(trace_id, room)

        for turn in transcript:
            opik.log_conversation_item(trace_id, turn.role, turn.content)
        opik.log_full_transcript(trace_id, transcript)
        for tc in tool_calls:
            opik.log_tool_call(trace_id, tc.tool_name, tc.arguments, tc.result)

        analysis = analyze_call(
            transcript=transcript,
            tool_calls=tool_calls,
            call_duration=duration,
        )
        opik.log_post_call_analysis(trace_id, analysis)

        eval_results = opik.run_evaluation(trace_id, transcript, analysis)
        eval_results.append(opik.run_llm_evaluation(trace_id, transcript, analysis))

        print("\n" + "=" * 60)
        print(label)
        print("=" * 60)
        print(f"Outcome: {analysis.call_outcome}")
        print(f"Appointment Booked: {analysis.appointment_booked}")
        print(f"Patient Agreed But Not Booked: {analysis.patient_agreed_not_booked}")
        if analysis.appointment_details:
            print(f"Appointment Details: {json.dumps(analysis.appointment_details, indent=2)}")
        print(f"Topics Discussed: {', '.join(analysis.key_topics_discussed)}")
        print(f"Sentiment: {analysis.sentiment}")
        print(f"Summary: {analysis.summary}")
        print(f"\nOpik Trace ID: {trace_id}")
        print(f"Opik Project: {config['opik_project']}")
        print("\nEVALUATION RESULTS:")
        for er in eval_results:
            status = "PASS" if er.passed else "FAIL"
            print(f"  [{status}] {er.metric_name}: {er.score:.2f} - {er.reason}")

    opik.flush()
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Healthcare Voice Agent")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("dev", help="Run in local dev mode")
    subparsers.add_parser("start", help="Run in production outbound mode")

    call_parser = subparsers.add_parser(
        "call",
        help="One-command outbound call: starts worker, dispatches, dials, exits on end",
    )
    call_parser.add_argument("--phone", help="Phone number to call")
    call_parser.add_argument("--name", help="Patient name")
    call_parser.add_argument("--patient-id", help="Patient ID")
    call_parser.add_argument("--biomarkers", help="JSON string of biomarker data")
    call_parser.add_argument(
        "--worker-wait",
        type=float,
        default=8.0,
        help="Seconds to wait for the worker to register before dispatching (default: 8)",
    )
    call_parser.add_argument(
        "--detach",
        action="store_true",
        help="Run the worker as a subprocess instead of a background thread",
    )

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
    elif args.command == "call":
        run_call(args)
    elif args.command == "dispatch":
        run_dispatch(args)
    elif args.command == "analyze":
        run_analyze()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
