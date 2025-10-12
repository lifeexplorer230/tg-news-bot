import importlib.util
import os
import time
from pathlib import Path


def _load_healthcheck_module():
    module_path = Path(__file__).resolve().parents[1] / "docker" / "healthcheck.py"
    spec = importlib.util.spec_from_file_location("marketplace_healthcheck", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_healthcheck_success(tmp_path):
    module = _load_healthcheck_module()
    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("ping")

    os.environ["HEARTBEAT_PATH"] = str(heartbeat)
    os.environ["HEARTBEAT_MAX_AGE"] = "3600"

    try:
        assert module.main() == 0
    finally:
        os.environ.pop("HEARTBEAT_PATH", None)
        os.environ.pop("HEARTBEAT_MAX_AGE", None)


def test_healthcheck_stale_file(tmp_path):
    module = _load_healthcheck_module()
    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("old")

    # set mtime to past
    stale_time = time.time() - 400
    Path(heartbeat).touch(exist_ok=True)
    os.utime(str(heartbeat), (stale_time, stale_time))

    os.environ["HEARTBEAT_PATH"] = str(heartbeat)
    os.environ["HEARTBEAT_MAX_AGE"] = "60"

    try:
        assert module.main() == 1
    finally:
        os.environ.pop("HEARTBEAT_PATH", None)
        os.environ.pop("HEARTBEAT_MAX_AGE", None)
