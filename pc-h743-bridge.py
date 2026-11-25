"""Receive-only telemetry from one identified USB controller to its pinned Pi."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pc_h743_route as route
from pc_h743_packets import Packetizer


PROFILE = Path(os.environ.get("H743_BRIDGE_PROFILE", Path.home() / ".h743-pc-bridge" / "bridge.json"))
STATE_DIR = PROFILE.parent / "runtime"
STOP = STATE_DIR / "bridge.stop"


def publish(state, **fields):
    status = dict(state=state, updated_unix=time.time(), pid=os.getpid(), serial_writes=0, **fields)
    target = STATE_DIR / "bridge-status.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(status), encoding="utf-8")
    try:
        os.replace(temporary, target)
    except PermissionError as error:
        if getattr(error, "winerror", None) not in (5, 32, 33):
            raise
        # An open Windows reader may temporarily deny rename. The previous
        # complete record expires normally; the next poll publishes a fresh one.
        return


def pause():
    deadline = time.monotonic() + 2
    while not STOP.exists() and time.monotonic() < deadline:
        time.sleep(.1)


def forward(port, child):
    sequence = sent = 0
    packets = Packetizer()
    last_publish = 0
    last_read = time.monotonic()
    while not STOP.exists() and child.poll() is None and not child.pi_receipts.clock_changed.is_set():
        captured = time.monotonic()
        if not child.capture_clock.current(captured) or captured - last_read > .75:
            break
        if port.in_waiting > 8192:
            port.reset_input_buffer()
            packets.abandon()
            last_read = captured
            continue
        data = port.read(min(4096, max(1, port.in_waiting)))
        last_read = time.monotonic()
        if (last_read - captured > .75 or not child.capture_clock.current(last_read)
                or child.pi_receipts.clock_changed.is_set()):
            break
        for payload, first_capture in packets.push(data, captured):
            sequence += 1
            frame = dict(seq=sequence, received_unix=child.capture_clock.epoch(first_capture),
                         data=base64.b64encode(payload).decode())
            child.stdin.write(json.dumps(frame, separators=(",", ":")).encode() + b"\n")
            child.stdin.flush()
            sent += len(payload)
        if time.monotonic() - last_publish > 1:
            publish("forwarding_usb_bytes", bytes_forwarded=sent, port=port.port, receiver_preflight=True,
                    clock_rtt_ms=round(child.capture_clock.rtt * 1000, 1), **packets.status(last_read),
                    **child.pi_receipts.status(last_read))
            last_publish = time.monotonic()


def serve(serial, list_ports):
    attempt = 0
    next_fast_retry = 0.0
    while not STOP.exists():
        child = None
        port = None
        try:
            identity, config = route.private_profile(PROFILE)
            matches = route.matching_ports(list_ports.comports(), identity)
            if len(matches) != 1:
                publish("waiting_for_identified_h743_usb")
            else:
                peers, options = route.saved_route(config)
                peer = peers[attempt % len(peers)]
                attempt += 1
                publish("waiting_for_pinned_pi_receiver")
                child = route.open_receiver(options, peer, STOP.exists)
                if child is not None and not STOP.exists():
                    # Re-enumerate after the handshake to handle unplug/replacement.
                    current = route.matching_ports(list_ports.comports(), identity)
                    if len(current) == 1 and current[0].device == matches[0].device:
                        port = serial.Serial(port=None, baudrate=115200, timeout=.2)
                        port.dtr = False
                        port.rts = False
                        port.port = current[0].device
                        port.open()
                        port.reset_input_buffer()
                        # On disconnect retry the working route before moving on.
                        attempt -= 1
                        forward(port, child)
                        if child.pi_receipts.clock_changed.is_set():
                            publish("recalibrating_pi_clock")
                            now = time.monotonic()
                            if now >= next_fast_retry:
                                # Retry the verified endpoint immediately once. Repeated
                                # steps during startup still use the normal backoff.
                                next_fast_retry = now + 2
                                continue
        except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError, serial.SerialException):
            publish("reconnecting")
        finally:
            try:
                if port is not None:
                    port.close()
            finally:
                route.close_receiver(child)
        pause()


def main():
    if os.name != "nt":
        raise SystemExit("The sender requires Windows.")


    import serial
    from serial.tools import list_ports
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, False, "Local\\H743_PC_TELEMETRY_RECEIVE_ONLY")
    if not mutex:
        raise OSError("Cannot acquire bridge mutex")
    if kernel.GetLastError() == 183:
        kernel.CloseHandle(mutex)
        return
    try:
        (STATE_DIR / "bridge.pid").write_text(str(os.getpid()))
        serve(serial, list_ports)
    finally:
        try:
            publish("stopped")
        finally:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
