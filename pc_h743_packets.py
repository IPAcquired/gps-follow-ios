"""Preserve MAVLink packet boundaries and count CRC-verified flight heartbeats."""
from collections import deque


def heartbeat_ok(packet, header, payload_length):
    # HEARTBEAT is message zero in MAVLink 1 and 2. Its CRC_EXTRA is 50.
    # A MAVLink 2 frame may truncate trailing zeros but requires version 3 here.
    if payload_length != 9:
        return False
    crc = 0xFFFF
    for byte in (*packet[1:header + payload_length], 50):
        mixed = byte ^ (crc & 255)
        mixed ^= (mixed << 4) & 255
        crc = (crc >> 8) ^ (mixed << 8) ^ (mixed << 3) ^ (mixed >> 4)
    return int.from_bytes(packet[header + payload_length:header + payload_length + 2], "little") == crc


class Packetizer:
    def __init__(self):
        self.pending = bytearray()
        self.captures = deque()
        self.count = self.verified = self.expected = self.crc_errors = self.raw_count = 0
        self.discarded = 0
        self.last_expected = None
        self.last_source = None

    def consume(self, size):
        captured = self.captures[0][1]
        data = bytes(self.pending[:size])
        del self.pending[:size]
        remaining = size
        while remaining:
            available, stamp = self.captures.popleft()
            if available > remaining:
                self.captures.appendleft((available - remaining, stamp))
                break
            remaining -= available
        return data, captured

    def abandon(self):
        self.discarded += len(self.pending)
        self.pending.clear()
        self.captures.clear()

    def push(self, incoming, captured):
        if self.captures and captured - self.captures[0][1] > .75:
            self.abandon()
        if incoming:
            self.pending.extend(incoming)
            self.captures.append((len(incoming), captured))
        records = []
        while self.pending:
            data = self.pending
            if data[0] not in (0xFE, 0xFD):
                boundaries = [pos for pos in (data.find(0xFE), data.find(0xFD)) if pos >= 0]
                size = min(4096, min(boundaries) if boundaries else len(data))
                self.raw_count += size
                records.append((*self.consume(size), False))
                continue
            is_v2 = data[0] == 0xFD
            header = 10 if is_v2 else 6
            if len(data) < header:
                break
            payload = data[1]
            msg = int.from_bytes(data[7:10], "little") if is_v2 else data[5]
            signed = is_v2 and bool(data[2] & 1)
            if (is_v2 and data[2] & ~1) or (msg == 0 and payload != 9):
                self.raw_count += 1
                records.append((*self.consume(1), False))
                continue
            size = header + payload + 2 + (13 if signed else 0)
            if len(data) < size:
                break
            is_heartbeat = msg == 0 and heartbeat_ok(data, header, payload)
            if msg == 0 and not is_heartbeat:
                self.crc_errors += 1
                self.raw_count += 1
                records.append((*self.consume(1), False))
                continue
            packet, first_capture = self.consume(size)
            self.count += 1
            if is_heartbeat:
                self.verified += 1
                system, component = packet[5:7] if is_v2 else packet[3:5]
                vehicle, autopilot, _, _, version = packet[header + 4:header + 9]
                self.last_source = (system, component)
                if system == component == 1 and vehicle != 6 and autopilot == 3 and version == 3:
                    self.expected += 1
                    self.last_expected = first_capture
            records.append((packet, first_capture, is_heartbeat))
        return self.group(records)

    @staticmethod
    def group(records):
        # Each heartbeat has its own <= PIPE_BUF relay record. Other complete
        # packets from a serial read may share one record, retaining the oldest stamp.
        data = bytearray()
        stamp = None
        for packet, captured, heartbeat in records:
            if data and (heartbeat or len(data) + len(packet) > 4096):
                yield bytes(data), stamp
                data.clear()
                stamp = None
            if heartbeat:
                yield packet, captured
            else:
                data.extend(packet)
                if stamp is None:
                    stamp = captured
        if data:
            yield bytes(data), stamp

    def status(self, now):
        return dict(usb_packets_framed=self.count, usb_raw_bytes=self.raw_count,
                    usb_heartbeats_crc_valid=self.verified, usb_heartbeats_expected=self.expected,
                    usb_heartbeat_crc_errors=self.crc_errors, usb_partial_bytes_discarded=self.discarded,
                    usb_heartbeat_source=list(self.last_source) if self.last_source else None,
                    usb_expected_heartbeat_age_s=round(now-self.last_expected, 2) if self.last_expected is not None else None)
