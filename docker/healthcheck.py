#!/usr/bin/env python3
"""Healthcheck for Marketplace News Bot containers."""
# ruff: noqa: T201
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    """Validate heartbeat freshness."""
    heartbeat_path = Path(os.environ.get("HEARTBEAT_PATH", "/app/logs/listener.heartbeat"))
    max_age = int(os.environ.get("HEARTBEAT_MAX_AGE", "180"))

    if not heartbeat_path.exists():
        print(f"heartbeat file missing: {heartbeat_path}", file=sys.stderr)
        return 1

    try:
        mtime = heartbeat_path.stat().st_mtime
    except OSError as exc:  # noqa: BLE001
        print(f"failed to read heartbeat: {exc}", file=sys.stderr)
        return 1

    age = time.time() - mtime
    if age > max_age:
        print(f"heartbeat too old: {age:.0f}s", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
