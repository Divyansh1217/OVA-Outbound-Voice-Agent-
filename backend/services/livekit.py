"""LiveKit agent-dispatch service."""

from __future__ import annotations

import logging

from config import load_config
from livekit import api

logger = logging.getLogger(__name__)

AGENT_NAME = "healthcare-caller"


async def dispatch_agent_call(room_name: str, metadata_json: str, agent_name: str = AGENT_NAME) -> None:
    """Create an agent dispatch via the LiveKit API.

    Requires the LiveKit worker to be running (`python main.py start`).
    Raises on failure so the tracking task can mark the call as errored.
    """
    config = load_config()
    async with api.LiveKitAPI(
        url=config["livekit_url"],
        api_key=config["livekit_api_key"],
        api_secret=config["livekit_api_secret"],
    ) as lkapi:
        await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=agent_name,
                room=room_name,
                metadata=metadata_json,
            )
        )
        logger.info("Dispatched agent job to room %s", room_name)