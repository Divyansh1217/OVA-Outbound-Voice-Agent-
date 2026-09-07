"""Standalone AI Gateway: rate limiting, throttling, circuit breaker, retry, guardrails, Opik logging.

Framework-agnostic. Uses the OpenAI Python SDK pointed at any compatible provider (Groq, OpenAI, etc.).

Usage standalone:
    from ai_gateway import AIGateway, GatewayConfig
    gw = AIGateway(config=GatewayConfig(rate_limit_rpm=30), provider="groq", api_key="gsk_xxx", model="openai/gpt-oss-120b")
    result = await gw.generate_text(messages=[{"role":"user","content":"Hello"}])
    gw.close()

Usage from LiveKit:
    from gateway_llm import GatewayLLM
    llm = GatewayLLM(model="openai/gpt-oss-120b", api_key="gsk_xxx")
    session = AgentSession(llm=llm, ...)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RateLimitConfig:
    """Token-bucket rate limiter configuration."""
    rpm: int = 20          # requests per minute
    tpm: int = 200_000     # tokens per minute (approximate, based on input estimate)
    burst: int = 5         # max burst above sustained rate


@dataclass
class ThrottleConfig:
    """Concurrency / throttling configuration."""
    max_concurrent: int = 5       # max simultaneous LLM calls
    max_queue: int = 10           # max waiting requests before rejection
    queue_timeout: float = 30.0   # seconds to wait in queue before timeout


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5     # failures before opening
    cooldown_seconds: float = 60.0 # time before half-open
    half_open_max: int = 2         # probe requests in half-open state


@dataclass
class RetryConfig:
    """Retry with exponential backoff."""
    max_retries: int = 3
    base_delay: float = 1.0        # seconds
    max_delay: float = 30.0
    retryable_status_codes: list[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])


@dataclass
class GuardrailConfig:
    """Content guardrails."""
    # Input checks
    max_input_length: int = 4000
    blocked_keywords: list[str] = field(default_factory=lambda: [
        "ignore previous instructions", "ignore all instructions",
        "system prompt", "jailbreak",
    ])
    # Medical safety
    require_disclaimer_on_medical: bool = True
    # Output checks
    max_output_length: int = 4000
    blocked_output_patterns: list[str] = field(default_factory=lambda: [
        r"\bi am a (?:real|human|licensed) doctor\b",
        r"\bguarantee\w*\s+\S+\s+(?:cure|treatment|result|recovery)\b",
        r"\b100%\s+(?:cure|effective|works?)\b",
        r"\b(?:stop|discontinue)\s+(?:all\s+)?(?:your\s+)?medication\b",
        r"\b(?:cures?|heals?)\s+(?:\S+\s+){0,3}(?:instantly|immediately|overnight)\b",
    ])
    pii_patterns: list[str] = field(default_factory=lambda: [
        r"\b\d{3}-\d{2}-\d{4}\b",         # SSN
        r"\b\d{16}\b",                      # credit card (16 digits)
    ])


@dataclass
class GatewayConfig:
    """Top-level gateway configuration."""
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    throttle: ThrottleConfig = field(default_factory=ThrottleConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)


# ---------------------------------------------------------------------------
# Rate Limiter (token bucket)
# ---------------------------------------------------------------------------

class TokenBucketRateLimiter:
    """Async token-bucket rate limiter with per-key support."""

    def __init__(self, rpm: int, tpm: int, burst: int = 5):
        self.rpm = rpm
        self.tpm = tpm
        self.burst = burst
        self._lock = asyncio.Lock()
        self._tokens: dict[str, float] = defaultdict(lambda: float(self.rpm))
        self._last_refill: dict[str, float] = defaultdict(time.monotonic)
        self._token_counts: dict[str, float] = defaultdict(lambda: float(self.rpm))

    async def acquire(self, key: str = "default") -> bool:
        """Try to acquire a request permit. Returns False if rate limited."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill[key]
            self._last_refill[key] = now

            # Refill tokens
            refill = elapsed * (self.rpm / 60.0)
            self._token_counts[key] = min(
                float(self.rpm + self.burst),
                self._token_counts[key] + refill,
            )

            if self._token_counts[key] >= 1.0:
                self._token_counts[key] -= 1.0
                return True
            return False

    def tokens_remaining(self, key: str = "default") -> float:
        return self._token_counts[key]


class TokenBucketTPMLimiter:
    """Approximate TPM limiter using estimated token counts."""

    def __init__(self, tpm: int):
        self.tpm = tpm
        self._lock = asyncio.Lock()
        self._tokens: float = float(tpm)
        self._last_refill: float = time.monotonic()

    async def acquire(self, estimated_tokens: int) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._last_refill = now
            self._tokens = min(float(self.tpm), self._tokens + elapsed * (self.tpm / 60.0))
            if self._tokens >= estimated_tokens:
                self._tokens -= estimated_tokens
                return True
            return False


# ---------------------------------------------------------------------------
# Throttler (concurrency limiter with fair queue)
# ---------------------------------------------------------------------------

class Throttler:
    """Async semaphore-based throttler with bounded queue."""

    def __init__(self, max_concurrent: int, max_queue: int, queue_timeout: float):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue_size = 0
        self._max_queue = max_queue
        self._queue_timeout = queue_timeout
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Acquire a throttle permit. Returns False if queue is full."""
        async with self._lock:
            if self._queue_size >= self._max_queue:
                return False
            self._queue_size += 1
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._queue_timeout)
            return True
        except asyncio.TimeoutError:
            async with self._lock:
                self._queue_size -= 1
            return False

    def release(self):
        self._semaphore.release()
        asyncio.get_event_loop().call_soon(self._decrement_queue)

    def _decrement_queue(self):
        if self._queue_size > 0:
            self._queue_size -= 1


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Failure-tracking circuit breaker with cooldown and half-open probing."""

    def __init__(self, failure_threshold: int, cooldown_seconds: float, half_open_max: int):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max = half_open_max
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_probes = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_probes = 0
                self._success_count = 0
        return self._state

    async def record_success(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Circuit breaker: HALF_OPEN -> CLOSED (recovered)")
            elif self._state == CircuitState.CLOSED:
                self._failure_count = max(0, self._failure_count - 1)

    async def record_failure(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._last_failure_time = time.monotonic()
                logger.warning("Circuit breaker: HALF_OPEN -> OPEN (probe failed)")
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.monotonic()
                    logger.warning(
                        "Circuit breaker: CLOSED -> OPEN (failures=%d)", self._failure_count
                    )

    def is_available(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)


# ---------------------------------------------------------------------------
# Retry Policy
# ---------------------------------------------------------------------------

class RetryPolicy:
    """Exponential backoff with jitter for transient failures."""

    def __init__(self, max_retries: int, base_delay: float, max_delay: float, retryable_codes: list[int]):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retryable_codes = retryable_codes

    def should_retry(self, attempt: int, status_code: int | None = None) -> bool:
        if attempt >= self.max_retries:
            return False
        if status_code is not None and status_code not in self.retryable_codes:
            return False
        return True

    def delay_for(self, attempt: int) -> float:
        import random
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter = random.uniform(0, delay * 0.3)
        return delay + jitter


# ---------------------------------------------------------------------------
# Guardrail Engine
# ---------------------------------------------------------------------------

class GuardrailViolation(Exception):
    def __init__(self, rule: str, message: str, blocked_text: str = ""):
        self.rule = rule
        self.message = message
        self.blocked_text = blocked_text
        super().__init__(f"[Guardrail:{rule}] {message}")


class GuardrailEngine:
    """Content guardrails for input and output messages."""

    def __init__(self, config: GuardrailConfig):
        self.config = config
        self._compiled_blocked = [re.compile(kw, re.IGNORECASE) for kw in config.blocked_keywords]
        self._compiled_output = [re.compile(p, re.IGNORECASE) for p in config.blocked_output_patterns]
        self._compiled_pii = [re.compile(p) for p in config.pii_patterns]

    def check_input(self, messages: list[dict[str, str]]) -> None:
        """Validate input messages. Raises GuardrailViolation on failure."""
        for msg in messages:
            content = msg.get("content", "")
            if len(content) > self.config.max_input_length:
                raise GuardrailViolation(
                    "input_length",
                    f"Input exceeds max length ({len(content)} > {self.config.max_input_length})",
                    content[:100],
                )
            for pattern in self._compiled_blocked:
                if pattern.search(content):
                    raise GuardrailViolation(
                        "blocked_keyword",
                        "Input contains a blocked keyword/phrase",
                        content[:100],
                    )
            for pii in self._compiled_pii:
                if pii.search(content):
                    raise GuardrailViolation(
                        "pii_detected",
                        "Input contains personally identifiable information (SSN/credit card)",
                        content[:100],
                    )
        # Medical safety check: if input mentions medical advice requests, flag it
        medical_keywords = [
            "diagnos", "prescri", "what should i take for", "should i stop taking",
            "medical advice", "treatment plan",
        ]
        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        if last_user:
            content_lower = last_user.get("content", "").lower()
            if any(kw in content_lower for kw in medical_keywords):
                logger.warning("Guardrail: medical advice request detected in input")

    def check_output(self, text: str) -> str:
        """Validate output text. Returns (possibly redacted) text or raises GuardrailViolation."""
        if len(text) > self.config.max_output_length:
            raise GuardrailViolation(
                "output_length",
                f"Output exceeds max length ({len(text)} > {self.config.max_output_length})",
            )
        for pattern in self._compiled_output:
            if pattern.search(text):
                raise GuardrailViolation(
                    "unsafe_output",
                    "Output contains a potentially unsafe or unprofessional claim",
                    text[:200],
                )
        # PII redaction in output
        redacted = text
        for pii in self._compiled_pii:
            redacted = pii.sub("[REDACTED]", redacted)
        return redacted


# ---------------------------------------------------------------------------
# AIGateway
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    """Result of an LLM generation call."""
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    rate_limited: bool = False
    circuit_open: bool = False
    retries_attempted: int = 0
    guardrail_violation: str | None = None


class AIGateway:
    """AI Gateway with rate limiting, throttling, circuit breaking, retry, and guardrails.

    Wraps any OpenAI-compatible API (Groq, OpenAI, etc.).
    """

    def __init__(
        self,
        config: GatewayConfig | None = None,
        provider: str = "groq",
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "openai/gpt-oss-120b",
        opik_client: Any = None,
        opik_project: str | None = None,
    ):
        self.config = config or GatewayConfig()
        self.provider = provider
        self.model = model
        self._opik_client = opik_client
        self._opik_project = opik_project

        # Build the OpenAI client
        url = base_url
        if provider == "groq" and not url:
            url = "https://api.groq.com/openai/v1"
        elif provider == "openai" and not url:
            url = "https://api.openai.com/v1"
        self._client = AsyncOpenAI(api_key=api_key, base_url=url)

        # Gateway components
        self._rpm_limiter = TokenBucketRateLimiter(
            rpm=self.config.rate_limit.rpm,
            tpm=self.config.rate_limit.tpm,
            burst=self.config.rate_limit.burst,
        )
        self._tpm_limiter = TokenBucketTPMLimiter(tpm=self.config.rate_limit.tpm)
        self._throttler = Throttler(
            max_concurrent=self.config.throttle.max_concurrent,
            max_queue=self.config.throttle.max_queue,
            queue_timeout=self.config.throttle.queue_timeout,
        )
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker.failure_threshold,
            cooldown_seconds=self.config.circuit_breaker.cooldown_seconds,
            half_open_max=self.config.circuit_breaker.half_open_max,
        )
        self._retry_policy = RetryPolicy(
            max_retries=self.config.retry.max_retries,
            base_delay=self.config.retry.base_delay,
            max_delay=self.config.retry.max_delay,
            retryable_codes=self.config.retry.retryable_status_codes,
        )
        self._guardrails = GuardrailEngine(config=self.config.guardrails)

        # Metrics
        self._call_count = 0
        self._total_tokens = 0
        self._rate_limit_rejections = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "call_count": self._call_count,
            "total_tokens": self._total_tokens,
            "rate_limit_rejections": self._rate_limit_rejections,
            "circuit_breaker_state": self._circuit_breaker.state.value,
        }

    def _estimate_tokens(self, messages: list[dict[str, str]]) -> int:
        """Rough token estimate: ~4 chars per token."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return max(1, total_chars // 4)

    async def generate_text(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: list[dict[str, Any]] | None = None,
        trace_id: str | None = None,
    ) -> GenerationResult:
        """Generate a completion through the gateway.

        Applies: guardrails -> rate limit -> throttle -> circuit breaker -> retry -> provider call.
        """
        target_model = model or self.model
        self._call_count += 1

        # 1. Input guardrails
        try:
            self._guardrails.check_input(messages)
        except GuardrailViolation as e:
            logger.warning("Input guardrail violated: %s", e)
            return GenerationResult(
                content=f"[Blocked by guardrail: {e.rule}] {e.message}",
                model=target_model,
                guardrail_violation=e.rule,
            )

        # 2. Rate limit check
        estimated_tokens = self._estimate_tokens(messages)
        rpm_ok = await self._rpm_limiter.acquire()
        if not rpm_ok:
            self._rate_limit_rejections += 1
            logger.warning("Rate limit (RPM) exceeded — rejecting call")
            return GenerationResult(
                content="[Rate limited] Please try again shortly.",
                model=target_model,
                rate_limited=True,
            )

        tpm_ok = await self._tpm_limiter.acquire(estimated_tokens)
        if not tpm_ok:
            self._rate_limit_rejections += 1
            logger.warning("Rate limit (TPM) exceeded — rejecting call")
            return GenerationResult(
                content="[Token rate limit exceeded] Please try again shortly.",
                model=target_model,
                rate_limited=True,
            )

        # 3. Circuit breaker check
        if not self._circuit_breaker.is_available():
            logger.warning("Circuit breaker OPEN — rejecting call")
            return GenerationResult(
                content="[Service temporarily unavailable] The AI service is recovering.",
                model=target_model,
                circuit_open=True,
            )

        # 4. Throttle (concurrency limiter)
        throttled = await self._throttler.acquire()
        if not throttled:
            logger.warning("Throttle queue full — rejecting call")
            return GenerationResult(
                content="[Server busy] Too many concurrent requests.",
                model=target_model,
            )

        # 5. Call with retry
        last_exception: Exception | None = None
        retries = 0
        t0 = time.monotonic()

        try:
            for attempt in range(self._retry_policy.max_retries + 1):
                try:
                    response = await self._client.chat.completions.create(
                        model=target_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **({"tools": tools} if tools else {}),
                    )
                    await self._circuit_breaker.record_success()

                    choice = response.choices[0]
                    usage = {}
                    if response.usage:
                        usage = {
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                            "total_tokens": response.usage.total_tokens,
                        }
                        self._total_tokens += response.usage.total_tokens

                    content = choice.message.content or ""
                    tool_calls_raw = []
                    if choice.message.tool_calls:
                        tool_calls_raw = [
                            {"id": tc.id, "function": tc.function.name, "arguments": tc.function.arguments}
                            for tc in choice.message.tool_calls
                        ]

                    latency_ms = (time.monotonic() - t0) * 1000

                    # 6. Output guardrails
                    try:
                        content = self._guardrails.check_output(content)
                    except GuardrailViolation as e:
                        logger.warning("Output guardrail violated: %s", e)
                        content = f"[Response blocked by guardrail: {e.rule}] The AI response was filtered."

                    result = GenerationResult(
                        content=content,
                        model=target_model,
                        usage=usage,
                        finish_reason=choice.finish_reason or "",
                        tool_calls=tool_calls_raw,
                        latency_ms=latency_ms,
                        retries_attempted=retries,
                    )

                    # 7. Log to Opik
                    self._log_to_opik(messages, result, trace_id)

                    return result

                except Exception as exc:
                    last_exception = exc
                    retries = attempt + 1
                    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                    if isinstance(exc, httpx.HTTPStatusError):
                        status_code = exc.response.status_code

                    if not self._retry_policy.should_retry(attempt, status_code):
                        break

                    delay = self._retry_policy.delay_for(attempt)
                    logger.warning(
                        "LLM call failed (attempt %d/%d, status=%s): %s — retrying in %.1fs",
                        attempt + 1,
                        self._retry_policy.max_retries + 1,
                        status_code,
                        str(exc)[:120],
                        delay,
                    )
                    await asyncio.sleep(delay)

            # All retries exhausted
            await self._circuit_breaker.record_failure()
            latency_ms = (time.monotonic() - t0) * 1000
            return GenerationResult(
                content="[Error] Unable to generate a response. Please try again.",
                model=target_model,
                latency_ms=latency_ms,
                retries_attempted=retries,
                guardrail_violation=last_exception.__class__.__name__ if last_exception else None,
            )

        finally:
            self._throttler.release()

    def _log_to_opik(
        self,
        messages: list[dict[str, str]],
        result: GenerationResult,
        trace_id: str | None,
    ) -> None:
        """Log the generation call to Opik as an LLM span."""
        if not self._opik_client or not trace_id:
            return
        try:
            self._opik_client.span(
                trace_id=trace_id,
                name=f"llm_call_{self.provider}",
                type="llm",
                input={"messages": messages[-1:] if messages else [], "model": self.model},
                output={"content": result.content[:500], "finish_reason": result.finish_reason},
                metadata={
                    "provider": self.provider,
                    "model": self.model,
                    "latency_ms": result.latency_ms,
                    "tokens": result.usage,
                    "retries": result.retries_attempted,
                },
                model=self.model,
                provider=self.provider,
            )
        except Exception as e:
            logger.debug("Failed to log to Opik: %s", e)

    def check_guardrails(self, text: str, direction: str = "output") -> str | None:
        """Public guardrail check method for use by bridge layers.

        Returns redacted text on success, or raises GuardrailViolation.
        """
        if direction == "output":
            return self._guardrails.check_output(text)
        return text

    def close(self):
        """Flush pending Opik data."""
        if self._opik_client:
            try:
                self._opik_client.flush()
            except Exception:
                pass
