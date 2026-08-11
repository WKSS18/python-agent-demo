"""Small dependency-free HTTP load test for repeatable baseline measurements."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * p) - 1)
    return ordered[index]


def request_once(url: str, timeout: float) -> tuple[float, int]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
            status = response.status
    except Exception:
        status = 0
    return (time.perf_counter() - started) * 1000, status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(request_once, args.url, args.timeout) for _ in range(args.requests)]
        results = [future.result() for future in as_completed(futures)]
    wall = time.perf_counter() - started
    latencies = [latency for latency, _ in results]
    successes = sum(1 for _, status in results if 200 <= status < 400)
    report = {
        "timestamp": datetime.now(UTC).isoformat(), "url": args.url,
        "requests": args.requests, "concurrency": args.concurrency,
        "successes": successes, "errors": args.requests - successes,
        "error_rate": round((args.requests - successes) / args.requests, 4),
        "throughput_rps": round(args.requests / wall, 2),
        "duration_seconds": round(wall, 3),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2),
            "p50": round(percentile(latencies, .50), 2),
            "p95": round(percentile(latencies, .95), 2),
            "p99": round(percentile(latencies, .99), 2),
            "max": round(max(latencies), 2),
        },
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
