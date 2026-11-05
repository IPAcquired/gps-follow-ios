"""Desk-test candidate. Produces requests only; never sends flight commands.

Timestamps are local monotonic receipt times. UWB supplies slant range, not
heading, person recognition, or a guarantee of authenticated packets.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from enum import Enum
import math
import re
import statistics

TAG_ADDRESS = "NATE0001"
ANCHOR_ADDRESS = "DRONE001"
NETWORK_ID = "NATEUWB1"
UART_BAUD = 115_200
RF_CHANNEL = "5"
RF_BANDWIDTH = "0"
COUNTER_MASK = 0xFFFFFFFF

def finite(value: object) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)

def validate_aes_key(key: str) -> str:
    if not isinstance(key, str) or not re.fullmatch(r"[0-9A-F]{32}", key):
        raise ValueError("AES key must be 32 uppercase hexadecimal characters")
    if key == "0" * 32:
        raise ValueError("factory all-zero AES key is forbidden")
    return key

def radio_settings(aes_key: str, *, tag: bool) -> dict[str, str]:
    """Read each setting first; write only mismatches, then verify readback."""
    return {
        "MODE": "0" if tag else "1", "CHANNEL": RF_CHANNEL,
        "BANDWIDTH": RF_BANDWIDTH, "NETWORKID": NETWORK_ID,
        "ADDRESS": TAG_ADDRESS if tag else ANCHOR_ADDRESS,
        "CPIN": validate_aes_key(aes_key),
        **({"TAGD": "0,0"} if tag else {"RSSI": "1"}),
    }

def anchor_configuration(aes_key: str) -> tuple[str, ...]:
    """Desired settings, not an instruction to rewrite flash on every poll."""
    return ("AT", *(f"AT+{k}={v}" for k, v in radio_settings(aes_key, tag=False).items()))

def counter_payload(sequence: int) -> str:
    if type(sequence) is not int or not 0 <= sequence <= COUNTER_MASK:
        raise ValueError("invalid UWB counter")
    return f"{sequence:08X}"

def anchor_poll_command(sequence: int = 0) -> str:
    return f"AT+ANCHOR_SEND={TAG_ADDRESS},8,{counter_payload(sequence)}"

@dataclass(frozen=True)
class RangeSample:
    tag: str
    payload: str
    distance_m: float
    received_s: float
    rssi: int | None = None

@dataclass(frozen=True)
class VisionSample:
    target_id: str
    bearing_deg: float
    confidence: float
    received_s: float
    # Corrected for the camera mounting and aircraft attitude, not raw pixels.
    elevation_deg: float = 0.0

@dataclass(frozen=True)
class MotionRequest:
    state: str
    forward_mps: float = 0.0
    yaw_rate_dps: float = 0.0
    reason: str = ""

class GateState(str, Enum):
    DISABLED = "disabled"
    WARMUP = "warmup"
    FOLLOW = "follow"
    HOLD = "hold"
    PILOT = "pilot"

class LineFramer:
    """Bounded ASCII CRLF reader; overflow discards the entire damaged line."""
    def __init__(self, maximum: int = 128):
        if not 16 <= maximum <= 512:
            raise ValueError("invalid line limit")
        self.maximum = maximum
        self.buffer = bytearray()
        self.discard = False
        self.rejected = 0

    def feed(self, chunk: bytes) -> list[str]:
        if not isinstance(chunk, bytes) or len(chunk) > 4096:
            raise ValueError("invalid or excessive UART chunk")
        lines = []
        for byte in chunk:
            if byte == 10:
                if not self.discard and self.buffer.endswith(b"\r"):
                    content = self.buffer[:-1]
                    if content:
                        lines.append(content.decode("ascii"))
                elif not self.discard and self.buffer:
                    self.rejected += 1
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                if (byte != 13 and not 32 <= byte <= 126) or len(self.buffer) >= self.maximum:
                    self.buffer.clear()
                    self.discard = True
                    self.rejected += 1
                else:
                    self.buffer.append(byte)
        return lines

_ANCHOR = re.compile(
    r"^\+ANCHOR_RCV=(?P<tag>[A-Z0-9]{8}),8,(?P<data>[0-9A-F]{8}),"
    r"(?P<cm>\d{1,5}) cm(?:,(?P<rssi>-?\d{1,3}))?$"
)

def parse_anchor_line(line: str, now_s: float) -> RangeSample:
    if not isinstance(line, str) or len(line) > 128 or not finite(now_s) or now_s < 0:
        raise ValueError("invalid UWB input")
    match = _ANCHOR.fullmatch(line)
    if not match or match.group("tag") != TAG_ADDRESS:
        raise ValueError("malformed or unexpected UWB target")
    cm = int(match.group("cm"))
    rssi = int(match.group("rssi")) if match.group("rssi") is not None else None
    if not 0 < cm <= 10_000 or (rssi is not None and not -127 <= rssi <= 0):
        raise ValueError("UWB measurement outside accepted range")
    return RangeSample(TAG_ADDRESS, match.group("data"), cm / 100, now_s, rssi)

class FollowGate:
    RANGE_STALE_S = 0.50
    VISION_STALE_S = 0.30
    MIN_VISION_CONFIDENCE = 0.70
    MAX_RANGE_RATE_MPS = 8.0
    JUMP_ALLOWANCE_M = 0.50
    REQUIRED_GOOD_SAMPLES = 3
    DESIRED_DISTANCE_M = 5.0
    DISTANCE_DEADBAND_M = 0.50
    MAX_FORWARD_MPS = 1.50
    MAX_YAW_RATE_DPS = 25.0

    def __init__(self):
        self._ranges: deque[RangeSample] = deque(maxlen=5)
        self._good_run = 0
        self._last_counter: int | None = None
        self._last_counter_time: float | None = None
        self._last_evaluation: float | None = None
        self._cancelled = False
        self._enabled_last = False

    def _clear_measurements(self):
        self._ranges.clear()
        self._good_run = 0

    def reset_session(self):
        self._clear_measurements()
        self._last_counter = None
        self._last_counter_time = None

    def add_range(self, sample: RangeSample, now_s: float) -> bool:
        # Validate direct samples too, not just UART input.
        valid = (
            isinstance(sample, RangeSample) and sample.tag == TAG_ADDRESS
            and isinstance(sample.payload, str) and re.fullmatch(r"[0-9A-F]{8}", sample.payload)
            and finite(sample.distance_m) and 0 < sample.distance_m <= 100
            and finite(sample.received_s) and finite(now_s) and 0 <= sample.received_s <= now_s
            and now_s - sample.received_s < self.RANGE_STALE_S - 1e-9
            and (sample.rssi is None or type(sample.rssi) is int and -127 <= sample.rssi <= 0)
        )
        if not valid:
            self._clear_measurements()
            return False
        counter = int(sample.payload, 16)
        if self._last_counter is not None:
            delta = (counter - self._last_counter) & COUNTER_MASK
            if delta == 0:
                # A radio can keep replying after its wearable MCU freezes.
                # Duplicates must not refresh the controller heartbeat.
                return False
            if delta >= 0x80000000 or sample.received_s <= self._last_counter_time:
                self._cancelled = True
                self._clear_measurements()
                return False
        self._last_counter = counter
        self._last_counter_time = sample.received_s
        if self._ranges:
            previous = self._ranges[-1]
            dt = sample.received_s - previous.received_s
            if dt >= self.RANGE_STALE_S - 1e-9:
                self._clear_measurements()  # Recover with NEW samples only.
            elif abs(sample.distance_m - previous.distance_m) > self.JUMP_ALLOWANCE_M + self.MAX_RANGE_RATE_MPS * dt:
                self._clear_measurements()
                return False
        self._ranges.append(sample)
        self._good_run += 1
        return True

    def evaluate(self, now_s: float, vision: VisionSample | None, *,
                 follow_enabled: bool, pilot_override: bool,
                 navigation_healthy: bool, flight_mode_allowed: bool,
                 armed: bool = False, controller_link_healthy: bool = False,
                 obstacle_data_fresh: bool = False, path_clear: bool = False,
                 target_binding_confirmed: bool = False) -> MotionRequest:
        def stopped(state, reason):
            return MotionRequest(state.value, reason=reason)
        flags = (follow_enabled, pilot_override, navigation_healthy, flight_mode_allowed,
                 armed, controller_link_healthy, obstacle_data_fresh, path_clear,
                 target_binding_confirmed)
        if any(type(flag) is not bool for flag in flags):
            self._cancelled = True
            self._clear_measurements()
            return stopped(GateState.HOLD, "invalid authority flags")
        if not finite(now_s) or now_s < 0:
            self._cancelled = True
            self._clear_measurements()
            return stopped(GateState.HOLD, "invalid local clock")
        if self._last_evaluation is not None and now_s < self._last_evaluation:
            self._cancelled = True
            self._clear_measurements()
        self._last_evaluation = now_s
        if not follow_enabled:
            if self._enabled_last or self._cancelled:
                self.reset_session()
            self._enabled_last = False
            self._cancelled = False
            return stopped(GateState.DISABLED, "follow switch off")
        self._enabled_last = True
        if pilot_override:
            self._cancelled = True
            return stopped(GateState.PILOT, "pilot override; switch off before re-enabling")
        if self._cancelled:
            return stopped(GateState.HOLD, "session cancelled; switch off before re-enabling")
        if not all((armed, controller_link_healthy, navigation_healthy, flight_mode_allowed,
                    obstacle_data_fresh, path_clear, target_binding_confirmed)):
            self._clear_measurements()
            return stopped(GateState.HOLD, "flight authority, obstacle coverage or target binding unavailable")
        if not self._ranges or not 0 <= now_s - self._ranges[-1].received_s < self.RANGE_STALE_S - 1e-9:
            self._clear_measurements()
            return stopped(GateState.HOLD, "UWB stale or unavailable")
        if self._good_run < self.REQUIRED_GOOD_SAMPLES:
            return stopped(GateState.WARMUP, "waiting for three NEW consistent UWB samples")
        if (not isinstance(vision, VisionSample) or vision.target_id != TAG_ADDRESS
                or not all(finite(v) for v in (vision.bearing_deg, vision.elevation_deg, vision.confidence, vision.received_s))
                or not 0 <= now_s - vision.received_s < self.VISION_STALE_S - 1e-9
                or not self.MIN_VISION_CONFIDENCE <= vision.confidence <= 1.0
                or not -180 <= vision.bearing_deg <= 180 or not -45 <= vision.elevation_deg <= 45):
            return stopped(GateState.HOLD, "visual identity, geometry or bearing unavailable")
        horizontal = statistics.median(x.distance_m for x in self._ranges) * math.cos(math.radians(vision.elevation_deg))
        error = horizontal - self.DESIRED_DISTANCE_M
        # Never reverse into an unobserved rear sector; turn before advancing.
        forward = (min(self.MAX_FORWARD_MPS, 0.55 * error)
                   if error > self.DISTANCE_DEADBAND_M and abs(vision.bearing_deg) <= 30 else 0.0)
        yaw = max(-self.MAX_YAW_RATE_DPS, min(self.MAX_YAW_RATE_DPS, 0.8 * vision.bearing_deg))
        return MotionRequest(GateState.FOLLOW.value, forward, yaw, "validated model request; not a flight command")

def serial_utilization_hz(poll_hz: float = 10.0, bytes_per_cycle: int = 110) -> float:
    if not finite(poll_hz) or poll_hz < 0 or type(bytes_per_cycle) is not int or bytes_per_cycle < 0:
        raise ValueError("invalid link load")
    return poll_hz * bytes_per_cycle * 10 / UART_BAUD
