"""In-process metrics, exposed in Prometheus text format at /metrics.

No client library needed: counters and a fixed-bucket latency histogram per
route template. Multi-worker deployments scrape each worker (standard
Prometheus practice) or sit behind a statsd-style aggregator.
"""

from __future__ import annotations

import time
from collections import defaultdict

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

_requests: dict[tuple[str, str, int], int] = defaultdict(int)
_lat_sum: dict[str, float] = defaultdict(float)
_lat_count: dict[str, int] = defaultdict(int)
_lat_buckets: dict[tuple[str, float], int] = defaultdict(int)
_started = time.time()


def observe(method: str, route: str, status: int, seconds: float) -> None:
    _requests[(method, route, status)] += 1
    _lat_sum[route] += seconds
    _lat_count[route] += 1
    for b in BUCKETS:
        if seconds <= b:
            _lat_buckets[(route, b)] += 1


def render() -> str:
    lines = [
        "# HELP sitebot_uptime_seconds Seconds since process start.",
        "# TYPE sitebot_uptime_seconds gauge",
        f"sitebot_uptime_seconds {time.time() - _started:.0f}",
        "# HELP sitebot_requests_total HTTP requests by method, route, status.",
        "# TYPE sitebot_requests_total counter",
    ]
    for (method, route, status), n in sorted(_requests.items()):
        lines.append(
            f'sitebot_requests_total{{method="{method}",route="{route}",status="{status}"}} {n}'
        )
    lines += [
        "# HELP sitebot_request_duration_seconds Request latency histogram.",
        "# TYPE sitebot_request_duration_seconds histogram",
    ]
    for route in sorted(_lat_count):
        acc = 0
        for b in BUCKETS:
            acc = _lat_buckets[(route, b)]
            lines.append(
                f'sitebot_request_duration_seconds_bucket{{route="{route}",le="{b}"}} {acc}'
            )
        lines.append(
            f'sitebot_request_duration_seconds_bucket{{route="{route}",le="+Inf"}} '
            f"{_lat_count[route]}"
        )
        lines.append(
            f'sitebot_request_duration_seconds_sum{{route="{route}"}} {_lat_sum[route]:.3f}'
        )
        lines.append(
            f'sitebot_request_duration_seconds_count{{route="{route}"}} {_lat_count[route]}'
        )
    return "\n".join(lines) + "\n"
