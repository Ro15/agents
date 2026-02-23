"""
Observability & Telemetry — Task 6.1
Structured request tracing and Prometheus-format metrics.
Uses a simple in-process counter/histogram without external dependencies.
Exports via GET /metrics endpoint.
"""
from __future__ import annotations

import logging
import os
import time
import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

_ENABLED = os.getenv("TELEMETRY_ENABLED", "true").lower() in ("1", "true", "yes")
_SLOW_THRESHOLD_MS = int(os.getenv("TELEMETRY_SLOW_THRESHOLD_MS", "5000"))


# ── In-process metrics store ──────────────────────────────────────────────

class _MetricsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, value: float = 1.0, labels: Optional[dict] = None):
        key = _label_key(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, labels: Optional[dict] = None):
        """Record a histogram observation (e.g., latency in ms)."""
        key = _label_key(name, labels)
        with self._lock:
            buf = self._histograms[key]
            buf.append(value)
            if len(buf) > 10000:
                buf.pop(0)  # cap memory

    def prometheus_text(self) -> str:
        """Export all metrics in Prometheus text format."""
        lines = []
        with self._lock:
            for key, val in sorted(self._counters.items()):
                name, labels = _parse_label_key(key)
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name}{{{labels}}} {val}")
            for key, observations in sorted(self._histograms.items()):
                if not observations:
                    continue
                name, labels = _parse_label_key(key)
                n = len(observations)
                total = sum(observations)
                sorted_obs = sorted(observations)
                p50 = _percentile(sorted_obs, 0.50)
                p95 = _percentile(sorted_obs, 0.95)
                p99 = _percentile(sorted_obs, 0.99)
                lines.append(f"# TYPE {name}_ms summary")
                lines.append(f'{name}_ms{{quantile="0.5",{labels}}} {p50:.2f}')
                lines.append(f'{name}_ms{{quantile="0.95",{labels}}} {p95:.2f}')
                lines.append(f'{name}_ms{{quantile="0.99",{labels}}} {p99:.2f}')
                lines.append(f"{name}_ms_count{{{labels}}} {n}")
                lines.append(f"{name}_ms_sum{{{labels}}} {total:.2f}")
        return "\n".join(lines) + "\n"

    def snapshot(self) -> dict:
        """Return a JSON-friendly snapshot for /metrics debug endpoint."""
        result = {"counters": {}, "histograms": {}}
        with self._lock:
            for key, val in self._counters.items():
                result["counters"][key] = round(val, 4)
            for key, obs in self._histograms.items():
                if obs:
                    s = sorted(obs)
                    result["histograms"][key] = {
                        "count": len(s),
                        "p50_ms": round(_percentile(s, 0.5), 2),
                        "p95_ms": round(_percentile(s, 0.95), 2),
                        "p99_ms": round(_percentile(s, 0.99), 2),
                    }
        return result


def _percentile(sorted_vals: list, p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(len(sorted_vals) * p)
    return float(sorted_vals[min(idx, len(sorted_vals) - 1)])


def _label_key(name: str, labels: Optional[dict]) -> str:
    if not labels:
        return f"{name}|"
    label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}|{label_str}"


def _parse_label_key(key: str) -> tuple[str, str]:
    parts = key.split("|", 1)
    name = parts[0]
    labels = parts[1] if len(parts) > 1 else ""
    return name, labels


_store = _MetricsStore()


# ── Span context manager ──────────────────────────────────────────────────

class Span:
    def __init__(self, name: str, labels: Optional[dict] = None):
        self.name = name
        self.labels = labels or {}
        self._start: float = 0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.monotonic() - self._start) * 1000
        if _ENABLED:
            _store.observe(self.name, elapsed_ms, self.labels)
            if exc_type is not None:
                _store.inc(f"{self.name}_errors", labels=self.labels)
            else:
                _store.inc(f"{self.name}_calls", labels=self.labels)
            if elapsed_ms > _SLOW_THRESHOLD_MS:
                logger.warning(
                    f"SLOW SPAN: {self.name} took {elapsed_ms:.0f}ms "
                    f"(threshold: {_SLOW_THRESHOLD_MS}ms) labels={self.labels}"
                )


@contextmanager
def trace_span(name: str, **label_kwargs):
    """Context manager for tracing a code block."""
    with Span(name, labels=label_kwargs) as span:
        yield span


# ── Convenience helpers ───────────────────────────────────────────────────

def inc(name: str, value: float = 1.0, **labels):
    if _ENABLED:
        _store.inc(name, value, labels or None)


def observe_ms(name: str, value_ms: float, **labels):
    if _ENABLED:
        _store.observe(name, value_ms, labels or None)


def record_chat_request(
    plugin_id: str,
    model: str,
    duration_ms: float,
    cache_hit: bool,
    confidence: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
):
    """Record all metrics for a single chat request."""
    if not _ENABLED:
        return
    labels = {"plugin": plugin_id, "model": model}
    _store.observe("chat_request", duration_ms, labels)
    _store.inc("chat_requests_total", labels=labels)
    _store.inc("chat_cache_hits" if cache_hit else "chat_cache_misses", labels={"plugin": plugin_id})
    _store.inc("llm_tokens_in", float(tokens_in), labels={"model": model})
    _store.inc("llm_tokens_out", float(tokens_out), labels={"model": model})
    _store.inc("llm_cost_usd", cost_usd, labels={"model": model})
    _store.inc(f"confidence_{confidence}_total", labels={"plugin": plugin_id})


def prometheus_output() -> str:
    return _store.prometheus_text()


def metrics_snapshot() -> dict:
    return _store.snapshot()
