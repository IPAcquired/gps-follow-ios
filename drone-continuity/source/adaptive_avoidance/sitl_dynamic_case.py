import json
import math
import sys
import threading
import time
from pymavlink import mavutil


ENABLE = int(sys.argv[1])
OUT = sys.argv[2]


def connect(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # ArduPilot accepts GCS control messages only from MAV_GCS_SYSID
            # (255 by default).  Using another source silently discards RC
            # overrides and can make a failed harness look like a flight issue.
            m = mavutil.mavlink_connection("tcp:127.0.0.1:5760", source_system=255)
            if m.wait_heartbeat(timeout=3):
                return m
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("SITL heartbeat timeout")


def set_param(m, name, value, timeout=6):
    m.param_set_send(name, float(value))
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=1)
        if msg and str(msg.param_id).rstrip("\x00") == name:
            if math.isclose(float(msg.param_value), float(value), rel_tol=0, abs_tol=1e-4):
                return float(msg.param_value)
    raise RuntimeError(f"no param acknowledgement for {name}={value}")


def reboot(m):
    m.mav.command_long_send(m.target_system, m.target_component,
                            mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
                            0, 1, 0, 0, 0, 0, 0, 0)
    time.sleep(4)
    try:
        m.close()
    except Exception:
        pass
    return connect(35)


def set_mode(m, name):
    mapping = m.mode_mapping()
    mode = mapping[name]
    m.set_mode(mode)
    deadline = time.time() + 10
    while time.time() < deadline:
        hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
        if hb and hb.custom_mode == mode:
            return
    raise RuntimeError(f"mode {name} not accepted")


def send_wall(m, distance_cm=300):
    m.mav.distance_sensor_send(int(time.monotonic() * 1000) & 0xFFFFFFFF,
                               20, 800, distance_cm, 0, 10,
                               mavutil.mavlink.MAV_SENSOR_ROTATION_NONE, 0)


def request_interval(m, message_id, interval_us=100000):
    m.mav.command_long_send(m.target_system, 1,
                            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                            0, message_id, interval_us, 0, 0, 0, 0, 0)


def rc_override(m, throttle):
    m.mav.rc_channels_override_send(m.target_system, 1,
                                    1500, 1500, throttle, 1500,
                                    65535, 65535, 65535, 65535)


def await_command_ack(m, command, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = m.recv_match(type=["COMMAND_ACK", "STATUSTEXT"], blocking=True, timeout=1)
        if msg and msg.get_type() == "COMMAND_ACK" and msg.command == command:
            return int(msg.result)
    raise RuntimeError(f"no command acknowledgement for {command}")


class WallStream:
    """Keep MAVLink proximity fresh while blocking on mode/arm/takeoff ACKs."""
    def __init__(self, m, distance_cm=300):
        self.m = m
        self.distance_cm = distance_cm
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop_event.is_set():
            send_wall(self.m, self.distance_cm)
            time.sleep(0.05)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)


m = connect()
for key, value in (("PRX1_TYPE", 2),
                   ("AVOID_ENABLE", 3), ("AVOID_BEHAVE", 1),
                   ("AVOID_MARGIN", 1), ("AVOID_ADAP_EN", ENABLE)):
    set_param(m, key, value)
m = reboot(m)
request_interval(m, mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT)
request_interval(m, mavutil.mavlink.MAVLINK_MSG_ID_LOCAL_POSITION_NED)
wall = WallStream(m)
wall.start()

# Verify the reboot-latched parameter and establish the simulated flight.
set_mode(m, "STABILIZE")
for _ in range(400):
    m.recv_match(blocking=False)
    time.sleep(0.1)
m.mav.command_long_send(m.target_system, 1,
                        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                        0, 1, 0, 0, 0, 0, 0, 0)
deadline = time.time() + 20
messages = []
while time.time() < deadline:
    msg = m.recv_match(blocking=True, timeout=0.2)
    if msg and msg.get_type() == "STATUSTEXT":
        messages.append(msg.text)
    hb = msg if msg and msg.get_type() == "HEARTBEAT" else None
    if hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
        break
else:
    raise RuntimeError(f"SITL arm failed: {messages[-8:]}")

# Simulator-only physical takeoff.  RC overrides must originate from
# MAV_GCS_SYSID (255 by default), which connect() enforces above.
deadline = time.time() + 25
max_alt = 0.0
while time.time() < deadline:
    rc_override(m, 1900)
    gp = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=0.2)
    if gp:
        max_alt = max(max_alt, gp.relative_alt * 0.001)
        if gp.relative_alt > 3500:
            break
if max_alt < 3.0:
    raise RuntimeError(f"takeoff failed, max altitude {max_alt}")
for _ in range(10):
    rc_override(m, 1500)
    time.sleep(0.1)
set_mode(m, "GUIDED")

# Request 2 m/s directly toward a fixed 3 m front obstacle.  Capture the
# actual body/NED velocity reached after native avoidance processes the target.
samples = []
mask = 0b0000111111000111
start = time.time()
while time.time() - start < 8.0:
    m.mav.set_position_target_local_ned_send(
        int((time.time() - start) * 1000), m.target_system, m.target_component,
        mavutil.mavlink.MAV_FRAME_LOCAL_NED, mask,
        0, 0, 0, 2.0, 0.0, 0.0, 0, 0, 0, 0, 0)
    lp = m.recv_match(type="LOCAL_POSITION_NED", blocking=True, timeout=0.1)
    if lp and time.time() - start > 2.0:
        samples.append(float(lp.vx))

# Stop, land and disarm cleanly.
for _ in range(20):
    m.mav.set_position_target_local_ned_send(
        0, m.target_system, m.target_component, mavutil.mavlink.MAV_FRAME_LOCAL_NED,
        mask, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    time.sleep(0.05)
set_mode(m, "LAND")
deadline = time.time() + 30
while time.time() < deadline:
    hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
    if hb and not (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
        break
wall.stop()

result = {
    "adaptive_enabled": ENABLE,
    "baseline_m": 1.0,
    "wall_distance_m": 3.0,
    "requested_vx_mps": 2.0,
    "takeoff_max_alt_m": max_alt,
    "sample_count": len(samples),
    "mean_vx_mps": sum(samples) / len(samples) if samples else None,
    "max_vx_mps": max(samples) if samples else None,
    "min_vx_mps": min(samples) if samples else None,
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
