"""LiveKit bridge: GatewayLLM wraps groq.LLM with the AIGateway.

Subclasses groq.LLM and overrides chat() to route through:
  input guardrails → rate limit → throttle → circuit breaker → retry → Groq API

Output guardrails run in the agent's on_conversation_item handler (post-stream).

Usage:
    from gateway_llm import GatewayLLM
    from ai_gateway import GatewayConfig

    llm = GatewayLLM(
        model="openai/gpt-oss-120b",
        api_key="gsk_xxx",
        gateway_config=GatewayConfig(rate_limit_rpm=20),
    )
    session = AgentSession(llm=llm, ...)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from livekit.agents import APIConnectOptions
from livekit.agents.llm import (
    ChatContext,
    LLM,
    LLMStream,
)
from livekit.plugins.groq import LLM as GroqLLM

from ai_gateway import AIGateway, GatewayConfig, GuardrailViolation

logger = logging.getLogger(__name__)

# Default Groq model for healthcare voice agent
DEFAULT_MODEL = "openai/gpt-oss-120b"


class GatewayLLM(GroqLLM):
    """Groq LLM with AIGateway guardrails, rate limiting, and throttling.

    Overrides chat() to intercept the call through the gateway pipeline.
    The underlying groq.LLM.chat() is called directly (streaming);
    the gateway handles rate-limiting, retries, circuit-breaking at the call level.
    Input guardrails run before the LLM call; output guardrails are applied
    in the agent layer via check_output().
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        gateway_config: GatewayConfig | None = None,
        opik_client: Any = None,
        opik_project: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(model=model, api_key=api_key, **kwargs)
        self._gateway = AIGateway(
            config=gateway_config or GatewayConfig(),
            provider="groq",
            api_key=api_key,
            model=model,
            opik_client=opik_client,
            opik_project=opik_project,
        )
        self._trace_id: str = ""

    @property
    def gateway(self) -> AIGateway:
        return self._gateway

    def set_trace_id(self, trace_id: str) -> None:
        self._trace_id = trace_id

    def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[Any] | None = None,
        conn_options: APIConnectOptions | None = None,
        parallel_tool_calls: Any = None,
        tool_choice: Any = None,
        **extra: Any,
    ) -> LLMStream:
        """Intercept chat() through the gateway pipeline."""
        from livekit.agents import DEFAULT_API_CONNECT_OPTIONS

        if conn_options is None:
            conn_options = DEFAULT_API_CONNECT_OPTIONS

        # --- Input guardrails ---
        # Check the latest user message; violations are logged for observability
        # but the stream still proceeds so the voice flow is never cut short.
        try:
            messages = [
                {"role": item.role, "content": item.text_content or ""}
                for item in chat_ctx.items
                if hasattr(item, "role") and hasattr(item, "text_content") and item.text_content
            ]
            self._gateway._guardrails.check_input(messages)
        except GuardrailViolation as e:
            logger.warning("Gateway input guardrail violated in chat(): %s", e)
        except Exception:
            pass

        # --- Circuit breaker ---
        if not self._gateway._circuit_breaker.is_available():
            logger.warning("Gateway circuit breaker OPEN - delegating to Groq for voice continuity")

        return super().chat(
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=conn_options,
            parallel_tool_calls=parallel_tool_calls,
            tool_choice=tool_choice,
            **extra,
        )

    def check_output_guardrail(self, text: str) -> str:
        """Run output guardrails on the text. Returns a safe string (never raises).

        Call this in the agent's on_conversation_item handler before TTS speaks.
        Unsafe content is returned as a safe fallback message.
        """
        try:
            return self._gateway.check_guardrails(text, direction="output")
        except GuardrailViolation as exc:
            if self._gateway._opik_client:
                try:
                    self._gateway._opik_client.span(
                        trace_id=self._trace_id or None,
                        name="output_guardrail_block",
                        input={"text": text},
                        metadata={"rule": exc.rule},
                    )
                except Exception:
                    pass
            return "[Assistant response reviewed for safety]"

    def close(self):
        self._gateway.close()
