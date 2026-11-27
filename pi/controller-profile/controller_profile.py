"""Read-only controller identity, configured wiring and public board reference."""
import hashlib
import math
import os
from pathlib import Path
import stat

MODEL = "CORVON743V2"
BOARD_ID = 1229
REFERENCE_PATH = "libraries/AP_HAL_ChibiOS/hwdef/CORVON743V2/hwdef.dat"
REFERENCE_COMMIT = "1f36df1c90dfe41131f8fc565bbcf190be4b2a84"
REFERENCE_SHA256 = "bc9f212daaacab69091988c01f1f252d48b60366d25b906edadf78c6b0c8d734"
SENSOR_LINKS = {
    "flight_controller": {"controller": MODEL, "pi_port": "UART0", "peer_port": "UART4/TELEM2", "baud": 115200},
    "rplidar": {"device": "RPLIDAR C1", "pi_port": "UART2"},
    "matrix_lidar": {"device": "8x8 sensor", "pi_port": "UART7"},
    "camera": {"pi_port": "USB"},
}


def source_pair(identity):
    if not isinstance(identity, dict):
        return None
    pair = identity.get("system_id"), identity.get("component_id")
    return pair if all(type(v) is int and 1 <= v <= 255 for v in pair) else None


def verified_route(route):
    # The owner-accepted native route uses this UART. /dev/h743 is its legacy
    # udev alias. The similarly named USB alias selects an older board.
    if type(route) is not str:
        return False
    if route in ('/dev/ttyS0', '/dev/h743'):
        try:
            node=Path(route).resolve(strict=True)
            return str(node)=='/dev/ttyS0' and stat.S_ISCHR(node.stat().st_mode)
        except OSError:
            return False
    # The existing authenticated Windows receiver identifies the CORVON's
    # USB VID/PID and enrolled hardware serial before writing this owner FIFO.
    if route=='/run/orangepi-mavlink/pc-h743.fifo':
        try:
            st=Path(route).lstat()
            lock = Path(route + '.lock').lstat()
            if (not stat.S_ISFIFO(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077
                    or not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.getuid() or lock.st_mode & 0o077):
                return False
            for line in Path('/proc/locks').read_text().splitlines():
                fields=line.split()
                if len(fields)<6 or fields[1:4]!=['FLOCK','ADVISORY','WRITE']:continue
                device=fields[5].split(':')
                if len(device)==3 and (int(device[0],16),int(device[1],16),int(device[2])) == (
                    os.major(lock.st_dev),os.minor(lock.st_dev),lock.st_ino):
                    return True
            return False
        except (OSError, ValueError):
            return False
    return False


def controller_profile(flight, now, ttl=2.0):
    flight = flight if isinstance(flight, dict) else {}
    stamp = flight.get("last_heartbeat_unix")
    present = ((flight.get("connected") is True or flight.get("heartbeat_observed") is True)
               and type(stamp) in (int, float) and math.isfinite(stamp) and 0 < stamp <= now
               and now - stamp <= ttl)
    actual = source_pair(flight.get("h743_source"))
    expected = source_pair(flight.get("expected_source"))
    state = "unverified"
    if present and actual and expected:
        if actual != expected or flight.get("transport") in ("/dev/rfcomm0", "/dev/h743-usb"):
            state = "mismatch"
        elif verified_route(flight.get("transport")):
            state = "matching"
    return {"configured_model": MODEL, "configured_board_id": BOARD_ID,
            "source_state": state, "presence": "heartbeat" if present else "unknown"}


def board_reference():
    result = {"configured_model": MODEL, "configured_board_id": BOARD_ID, "source_file": REFERENCE_PATH,
              "source_commit": REFERENCE_COMMIT, "source_sha256": REFERENCE_SHA256,
              "upstream_url": f"https://github.com/ArduPilot/ardupilot/blob/{REFERENCE_COMMIT}/{REFERENCE_PATH}",
              "evidence_scope": "published_board_definition", "live_firmware_bytes_attested": False}
    try:
        data = Path(__file__).with_name(MODEL + ".hwdef.dat").read_bytes()
    except OSError:
        return {**result, "source_status": "unavailable"}
    if hashlib.sha256(data).hexdigest() != REFERENCE_SHA256:
        return {**result, "source_status": "hash_mismatch_refused"}
    lines = [line for line in data.decode("ascii", "replace").splitlines()
             if line.startswith(("MCU ", "APJ_BOARD_ID ", "SERIAL_ORDER ", "PA0 UART4", "PA1 UART4"))]
    return {**result, "source_status": "verified_offline_copy", "matching_lines": "\n".join(lines)}
