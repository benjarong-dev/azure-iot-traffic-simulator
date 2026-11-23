"""Command-line entrypoint for urban traffic and PM2.5 telemetry streaming."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import List, Optional

from .iot_publisher import TelemetryPublisher
from .telemetry_model import build_default_fleet


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream urban traffic & roadside PM2.5 telemetry to Azure IoT Hub."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between telemetry emission cycles (default: 5.0).",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=0,
        help="Number of cycles to emit before exiting (0 = run continuously).",
    )
    parser.add_argument(
        "--hour-override",
        type=float,
        default=None,
        help="Optional fixed local hour (0-23.9) to simulate peak/off-peak conditions.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible telemetry output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON payloads to stdout without connecting to Azure IoT Hub.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.interval < 0:
        sys.stderr.write("Error: --interval must be non-negative.\n")
        return 2

    stop_requested = False

    def _handle_signal(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        publisher = TelemetryPublisher(dry_run=args.dry_run)
    except (ValueError, RuntimeError) as exc:
        sys.stderr.write(f"Configuration error: {exc}\n")
        return 1

    fleet = build_default_fleet(seed=args.seed)
    cycle = 0

    try:
        while not stop_requested:
            cycle += 1
            for node in fleet:
                reading = node.next_reading(local_hour_override=args.hour_override)
                publisher.publish(reading)

            if args.ticks > 0 and cycle >= args.ticks:
                break

            if args.interval > 0 and not stop_requested:
                time.sleep(args.interval)
    finally:
        publisher.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
