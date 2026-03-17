"""
app/middleware/metrics.py
-------------------------
Simple in-memory metrics collection.

What are metrics?
  While logs tell you WHAT happened (discrete events),
  metrics tell you HOW MUCH is happening over time (aggregated numbers).

  Examples:
    - 4,231 requests in the last minute
    - Error rate: 0.8%
    - p95 latency: 340ms
    - Cache hit rate: 87%
    - Active DB connections: 7/10

Prometheus format:
  The industry standard for metrics. Azure Monitor, Grafana, and
  Datadog can all scrape Prometheus-format metrics. The format looks like:

    # HELP http_requests_total Total HTTP requests
    # TYPE http_requests_total counter
    http_requests_total{method="GET",path="/v1/courses",status="200"} 4231
    http_requests_total{method="POST",path="/v1/borrowings",status="201"} 89

  Labels (the {key="value"} parts) let you slice the data:
  "show me all POST requests to /v1/borrowings with status 201"

Why in-memory?
  For a single-instance deployment, in-memory is fine.
  For multiple instances (horizontal scaling), you'd use a shared
  metrics store like Prometheus Push Gateway or Azure Monitor.
  We keep it simple here — the pattern is what matters.

In production:
  Azure Application Insights does all this automatically when you
  include the opencensus-ext-azure package. We build it manually here
  so you understand what's happening under the hood.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


@dataclass
class MetricsStore:
    """
    Thread-safe in-memory metrics store.

    Uses a Lock for thread safety — multiple requests run concurrently
    and all write to these counters simultaneously.
    """
    _lock: Lock = field(default_factory=Lock)

    # Counters — always increasing numbers
    request_count: dict = field(default_factory=lambda: defaultdict(int))
    error_count: dict = field(default_factory=lambda: defaultdict(int))

    # Histograms — tracks latency distribution
    # We keep a simple list of recent durations (last 1000 requests per path)
    latencies: dict = field(default_factory=lambda: defaultdict(list))
    MAX_LATENCY_SAMPLES = 1000

    def record_request(self, method: str, path: str, status: int, duration_ms: float):
        """Record a completed request."""
        label = f"{method}:{path}"
        with self._lock:
            self.request_count[label] += 1
            self.request_count["total"] += 1

            if status >= 500:
                self.error_count[label] += 1
                self.error_count["total"] += 1

            # Keep latency samples capped
            samples = self.latencies[label]
            samples.append(duration_ms)
            if len(samples) > self.MAX_LATENCY_SAMPLES:
                samples.pop(0)

    def get_percentile(self, path_label: str, percentile: float) -> float:
        """Calculate latency percentile for a path."""
        with self._lock:
            samples = sorted(self.latencies.get(path_label, [0]))
            if not samples:
                return 0.0
            idx = int(len(samples) * percentile / 100)
            return samples[min(idx, len(samples) - 1)]

    def to_prometheus(self) -> str:
        """
        Export metrics in Prometheus text format.
        This is what /metrics returns — Prometheus or Azure Monitor scrapes it.
        """
        lines = []

        # Request totals
        lines.append("# HELP http_requests_total Total HTTP requests by method and path")
        lines.append("# TYPE http_requests_total counter")
        with self._lock:
            for label, count in self.request_count.items():
                if ":" in label:
                    method, path = label.split(":", 1)
                    lines.append(
                        f'http_requests_total{{method="{method}",path="{path}"}} {count}'
                    )

        # Error totals
        lines.append("# HELP http_errors_total Total HTTP 5xx errors")
        lines.append("# TYPE http_errors_total counter")
        with self._lock:
            for label, count in self.error_count.items():
                if ":" in label:
                    method, path = label.split(":", 1)
                    lines.append(
                        f'http_errors_total{{method="{method}",path="{path}"}} {count}'
                    )

        # Latency percentiles
        lines.append("# HELP http_request_duration_ms Request duration in milliseconds")
        lines.append("# TYPE http_request_duration_ms summary")
        with self._lock:
            for label in self.latencies:
                if ":" in label:
                    method, path = label.split(":", 1)
                    for p in [50, 95, 99]:
                        val = self.get_percentile(label, p)
                        lines.append(
                            f'http_request_duration_ms{{method="{method}",path="{path}",quantile="0.{p}"}} {val}'
                        )

        return "\n".join(lines) + "\n"


# Global metrics store — single instance shared across all requests
metrics = MetricsStore()


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Records metrics for every request.
    Runs alongside the logging middleware.
    """

    SKIP_PATHS = {"/metrics", "/health", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # Normalize path — replace IDs with {id} so we don't get
        # a separate metric for every single student/course ID
        # e.g. /v1/students/stu_10042 → /v1/students/{id}
        path = self._normalize_path(request.url.path)

        metrics.record_request(
            method=request.method,
            path=path,
            status=response.status_code,
            duration_ms=duration_ms,
        )

        return response

    def _normalize_path(self, path: str) -> str:
        """
        Replace path parameter values with {id} placeholder.

        Without this: /v1/students/stu_10042, /v1/students/stu_99999 → 2 metrics
        With this:    /v1/students/{id} → 1 metric for all student lookups

        Simple heuristic: if a path segment looks like an ID
        (contains underscore + alphanumeric), replace it.
        """
        parts = path.split("/")
        normalized = []
        for part in parts:
            # Detect ID-like segments (our format: prefix_uuid or prefix_number)
            if "_" in part and len(part) > 8:
                normalized.append("{id}")
            else:
                normalized.append(part)
        return "/".join(normalized)
