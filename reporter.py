"""Live call reporter: pushes transcript/status events and the final result to the dashboard backend.

If INTERNAL_API_URL is not configured (or the backend is down), the reporter
silently no-ops so calls never fail because the dashboard is offline.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CallReporter:
    """Batches conversation/status events and posts a final result payload."""

    def __init__(self, base_url: str, call_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.call_id = call_id
        self._client: Any | None = None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._task: asyncio.Task | None = None
        self._started = False

    @property
    def enabled(self) -> bool:
        return self._started

    def start(self) -> None:
        if not self.base_url:
            logger.info("INTERNAL_API_URL not set; skipping dashboard reporting")
            return
        try:
            import httpx

            self._client = httpx.AsyncClient(timeout=5)
            self._queue = asyncio.Queue()
            self._task = asyncio.create_task(self._flush_loop())
            self._started = True
        except Exception:
            logger.exception("Failed to start CallReporter")

    def push(self, event_type: str, payload: dict[str, Any]) -> None:
        """Queue an event to be flushed to the backend (fire-and-forget)."""
        if not self._started or not self._queue:
            return
        try:
            self._queue.put_nowait({"type": event_type, "data": payload})
        except Exception:
            pass

    async def _flush_loop(self) -> None:
        while True:
            try:
                if self._queue:
                    batch = [self._queue.get_nowait() for _ in range(20)]
                    await self._post_events(batch)
            except asyncio.QueueEmpty:
                pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Reporter flush error: %s", e)
            await asyncio.sleep(1)

    async def _post_events(self, batch: list[dict[str, Any]]) -> None:
        if not self._client:
            return
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/v1/internal/calls/{self.call_id}/events",
                json={"events": batch},
            )
            resp.raise_for_status()
        except Exception as e:
            logger.debug("Reporter event POST failed: %s", e)

    async def finish(self, result_payload: dict[str, Any]) -> None:
        """Flush queued events, post the final result, and shut down."""
        if not self._started or not self._client:
            return
        try:
            if self._queue:
                remaining = [self._queue.get_nowait() for _ in range(100)]
                if remaining:
                    await self._post_events(remaining)
        except asyncio.QueueEmpty:
            pass
        except Exception as e:
            logger.debug("Reporter flush-on-finish error: %s", e)

        try:
            resp = await self._client.post(
                f"{self.base_url}/api/v1/internal/calls/{self.call_id}/result",
                json=result_payload,
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.debug("Reporter result POST failed: %s", e)
        finally:
            self._started = False
            if self._task:
                self._task.cancel()
            try:
                await self._client.aclose()
            except Exception:
                pass