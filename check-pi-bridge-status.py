"""Pipe into python3 on the already pinned Pi. Output omits device identities and telemetry."""
import json
import time
from pathlib import Path


FIFO = "/run/orangepi-mavlink/pc-h743.fifo"
STATUS = Path("/run/orangepi-mavlink/status.json")


def sample(value, now):
    choice = value.get("transport")
    source = value.get("h743_source")
    expected = value.get("expected_source")
    source_ok = (isinstance(source, dict) and source == expected and
                 all(type(source.get(k)) is int and 1 <= source[k] <= 255 for k in ("system_id", "component_id")))
    beat = value.get("heartbeat_updated_unix")
    published = value.get("updated_unix")
    fresh = all(type(stamp) in (int, float) and 0 <= now - stamp <= 2 for stamp in (beat, published))
    valid = (choice == FIFO and value.get("connected") is True and source_ok and fresh and
             value.get("authority") == "read_only_no_mavlink_transmit")
    return valid, beat, choice if choice in (FIFO, "/dev/h743", "/dev/h743-usb", "/dev/rfcomm0") else "other"


def main():
    deadline = time.monotonic() + 15
    previous = None
    choice = "none"
    while time.monotonic() < deadline:
        try:
            value = json.loads(STATUS.read_text())
            valid, beat, choice = sample(value, time.time())
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            valid = False
        if valid:
            if previous is not None and beat > previous:
                print(json.dumps(dict(fifo_verified=True, distinct_fresh_heartbeats=2,
                                      disarmed=value.get("armed") is False, transport=choice)))
                return 0
            previous = beat
        else:
            previous = None
        time.sleep(.35)
    print(json.dumps(dict(fifo_verified=False, last_selected_transport=choice)))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
