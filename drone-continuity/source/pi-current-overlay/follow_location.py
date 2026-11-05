"""Ephemeral phone position observation. Never sends MAVLink or controls flight."""
from collections import deque
import math
import re
import threading
import time


class PhoneLocationStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.point = None
        self.epoch = None
        self.sequence = 0
        self.retired = deque(maxlen=32)
        self.state = 'unavailable'
        self.provenance = 'authenticated_display_report'

    def accept(self, payload, provenance="authenticated_display_report"):
        if provenance not in {"authenticated_display_report", "authenticated_phone_browser"}:
            raise ValueError("Invalid provenance")
        if not isinstance(payload, dict):
            raise ValueError('Expected phone position object')
        required = {'source', 'source_epoch', 'seq'}
        stopped = payload.get('stop') is True
        allowed = required | ({'stop'} if stopped else {'age_ms', 'lat', 'lon', 'accuracy_m'})
        if set(payload) != allowed or payload.get('source') != 'phone_gps':
            raise ValueError('Invalid phone position fields')
        epoch, sequence = payload['source_epoch'], payload['seq']
        if not isinstance(epoch, str) or not re.fullmatch('[0-9a-f]{32}', epoch):
            raise ValueError('Invalid phone source epoch')
        if type(sequence) is not int or not 1 <= sequence <= 4294967294:
            raise ValueError('Invalid phone sequence')
        if not stopped:
            age = payload['age_ms']
            if type(age) is not int or not 0 <= age <= 2500:
                raise ValueError('Phone position is too old')
            for key, low, high in (('lat', -90, 90), ('lon', -180, 180), ('accuracy_m', 0, 30)):
                value = payload[key]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError('Invalid phone position or accuracy')
            if payload['accuracy_m'] <= 0:
                raise ValueError('Phone accuracy must be known')
        with self.lock:
            if epoch in self.retired or (epoch == self.epoch and sequence <= self.sequence):
                raise ValueError('Duplicate or out-of-order phone position')
            if epoch != self.epoch:
                if self.epoch is not None:
                    self.retired.append(self.epoch)
                self.epoch = epoch
            self.sequence = sequence
            self.provenance = provenance
            self.point = None if stopped else {**payload, 'received': time.monotonic()}
            self.state = 'stopped' if stopped else 'fresh'
            return self._snapshot()

    def _snapshot(self):
        result = {'source': 'phone_gps', 'position_role': 'follow_target_observation',
                  'position_is_drone_gps': False, 'authority': 'advisory_only',
                  'mavlink_transmit': False, 'ttl_ms': 3000,
                  'provenance': self.provenance, 'status': self.state,
                  'memory_only': True, 'sequence': self.sequence}
        if self.point:
            age = self.point['age_ms'] + max(0, int((time.monotonic() - self.point['received']) * 1000))
            result.update(age_ms=age, accuracy_m=self.point['accuracy_m'])
            if age < 3000:
                result.update(status='fresh', lat=self.point['lat'], lon=self.point['lon'])
            else:
                result['status'] = 'stale'
                self.point = None
                self.state = 'stale'
        return result

    def snapshot(self):
        with self.lock:
            return self._snapshot()


PHONE_LOCATION = PhoneLocationStore()
