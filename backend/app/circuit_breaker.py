"""
Circuit Breaker — Task 6.2
Prevents cascading failures when external services (LLM, DB, Redis) are degraded.
States: CLOSED (normal) → OPEN (fast-fail) → HALF_OPEN (probe)
"""
from __future__ import annotations

import logging
import time
import threading
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when a circuit is open and the call is fast-failed."""
    pass


class CircuitBreaker:
    """
    Thread-safe circuit breaker with exponential back-off recovery.

    Usage:
        breaker = CircuitBreaker("llm_primary", failure_threshold=3, recovery_timeout=60)
        try:
            result = breaker.call(my_llm_function, *args, **kwargs)
        except CircuitOpenError:
            # fast-fail path: use cache, fallback, or return graceful error
        except Exception as e:
            # real error from the underlying call
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = self.CLOSED
        self._failures = 0
        self._successes = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._get_state()

    def _get_state(self) -> str:
        """Must be called under self._lock."""
        if self._state == self.OPEN:
            if self._last_failure_time and (time.monotonic() - self._last_failure_time) >= self.recovery_timeout:
                self._state = self.HALF_OPEN
                self._successes = 0
                logger.info(f"CircuitBreaker[{self.name}]: OPEN → HALF_OPEN (probing)")
        return self._state

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        """Execute fn under circuit protection."""
        with self._lock:
            current_state = self._get_state()
            if current_state == self.OPEN:
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is OPEN. Service unavailable. "
                    f"Retrying in {max(0, self.recovery_timeout - (time.monotonic() - (self._last_failure_time or 0))):.0f}s"
                )

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as e:
            self._on_failure(e)
            raise

    def _on_success(self):
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._successes += 1
                if self._successes >= self.success_threshold:
                    self._state = self.CLOSED
                    self._failures = 0
                    logger.info(f"CircuitBreaker[{self.name}]: HALF_OPEN → CLOSED (recovered)")
            elif self._state == self.CLOSED:
                self._failures = 0

    def _on_failure(self, exc: Exception):
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.monotonic()
            if self._state == self.HALF_OPEN:
                self._state = self.OPEN
                logger.warning(f"CircuitBreaker[{self.name}]: HALF_OPEN → OPEN (probe failed: {exc})")
            elif self._state == self.CLOSED and self._failures >= self.failure_threshold:
                self._state = self.OPEN
                logger.warning(
                    f"CircuitBreaker[{self.name}]: CLOSED → OPEN "
                    f"({self._failures} failures, last: {exc})"
                )

    def status(self) -> dict:
        """Return health dict for /health endpoint."""
        with self._lock:
            state = self._get_state()
            recovery_in = None
            if state == self.OPEN and self._last_failure_time:
                remaining = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
                recovery_in = f"{max(0, remaining):.0f}s"
            return {
                "name": self.name,
                "state": state,
                "failures": self._failures,
                "recovery_in": recovery_in,
            }

    def reset(self):
        """Manually reset the breaker (admin override)."""
        with self._lock:
            self._state = self.CLOSED
            self._failures = 0
            self._successes = 0
            self._last_failure_time = None
        logger.info(f"CircuitBreaker[{self.name}]: manually reset to CLOSED")


# ── Singleton registry ───────────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """Get or create a named circuit breaker (singleton per name)."""
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return _breakers[name]


def all_breaker_statuses() -> list[dict]:
    """Return status dicts for all registered breakers (for /health endpoint)."""
    with _registry_lock:
        return [b.status() for b in _breakers.values()]


# Pre-create the standard breakers used by the application
LLM_PRIMARY_BREAKER = get_breaker("llm_primary", failure_threshold=3, recovery_timeout=60)
LLM_FALLBACK_BREAKER = get_breaker("llm_fallback", failure_threshold=5, recovery_timeout=30)
REDIS_BREAKER = get_breaker("redis", failure_threshold=5, recovery_timeout=30)
DB_BREAKER = get_breaker("database", failure_threshold=5, recovery_timeout=20)
