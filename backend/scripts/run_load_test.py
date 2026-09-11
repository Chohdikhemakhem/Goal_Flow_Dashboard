from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT_DIR / "docs" / "reports" / "final" / "load_test_results.json"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 2)


def _request(url: str, timeout: float) -> dict[str, object]:
    started = time.perf_counter()
    try:
        with urlopen(Request(url, headers={"User-Agent": "microcred-load-test/1.0"}), timeout=timeout) as response:
            response.read()
            return {
                "status": response.status,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "ok": 200 <= response.status < 400,
            }
    except HTTPError as exc:
        return {
            "status": exc.code,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "ok": False,
        }
    except (URLError, TimeoutError) as exc:
        return {
            "status": 0,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "ok": False,
            "error": str(exc),
        }


def _docker_stats() -> str | None:
    try:
        completed = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        return completed.stdout.strip() or completed.stderr.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _run_step(url: str, concurrency: int, requests_count: int, timeout: float) -> dict[str, object]:
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_request, url, timeout) for _ in range(requests_count)]
        for future in as_completed(futures):
            results.append(future.result())

    elapsed_seconds = max(time.perf_counter() - started, 0.0001)
    latencies = [float(item["elapsed_ms"]) for item in results]
    errors = [item for item in results if not item["ok"]]
    return {
        "concurrency": concurrency,
        "requests": requests_count,
        "successful_requests": requests_count - len(errors),
        "errors": len(errors),
        "error_rate_percent": round((len(errors) / requests_count) * 100, 2),
        "throughput_requests_per_second": round(requests_count / elapsed_seconds, 2),
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else 0,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 2) if latencies else 0,
        },
        "docker_stats": _docker_stats(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a cautious stepped HTTP load test.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--concurrency", default="1,5,10,25,50")
    parser.add_argument("--requests-per-step", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    concurrency_levels = [int(value) for value in args.concurrency.split(",") if value.strip()]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        _request(args.url, args.timeout)
    steps = [
        _run_step(args.url, concurrency, args.requests_per_step, args.timeout)
        for concurrency in concurrency_levels
    ]
    highest_validated_concurrency = 0
    for step in steps:
        if step["errors"] != 0 or float(step["latency_ms"]["p95"]) >= 2000:
            break
        highest_validated_concurrency = int(step["concurrency"])
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target": args.url,
        "scope_note": (
            "Local HTTP baseline only. This is not a production capacity certification. "
            "Authenticated business workflows require a dedicated staging dataset and test accounts."
        ),
        "requests_per_step": args.requests_per_step,
        "steps": steps,
        "highest_validated_concurrency": highest_validated_concurrency,
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
