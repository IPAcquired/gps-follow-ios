from datetime import datetime, timezone
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import display_telemetry as display


def record(kind, values, stamp=99.8, source=(1, 1)):
    return {'message_type': kind, 'instance': 0, 'source_system_id': source[0], 'source_component_id': source[1],
            'values': values, 'field_updated_unix': {key: stamp for key in values},
            'field_fresh': {key: True for key in values}}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.flight = {'connected': True, 'fresh': True, 'last_heartbeat_unix': 99.5, 'armed': False,
                       'mode': 'STABILIZE', 'system_status': 'standby', 'h743_source': {'system_id': 1, 'component_id': 1},
                       'sensors': {'VFR_HUD:0': record('VFR_HUD', {'groundspeed_mps': 2.5, 'climb_mps': -.4}),
                                   'GPS_RAW_INT:0': record('GPS_RAW_INT', {'satellites': 12, 'hdop': .8})},
                       'battery': {'fresh': True, 'battery_id': 0, 'updated_unix': 99, 'voltage_v': 23.2,
                                   'source_system_id': 1, 'source_component_id': 1,
                                   'message_type': 'BATTERY_STATUS',
                                   'current_a': None, 'remaining_percent': None}}

    def snapshot(self, **kwargs):
        return display.build_snapshot(self.flight, {}, {'status': 'unavailable'}, now=100, pi={}, **kwargs)

    def test_measured_fields_and_unknown_values(self):
        value = self.snapshot()
        self.assertEqual(value['h743']['groundspeed_mps']['value'], 2.5)
        self.assertEqual(value['h743']['gps_satellites']['value'], 12)
        self.assertEqual(value['h743']['gps_hdop']['unit'], 'dimensionless')
        self.assertEqual(value['h743']['battery_voltage_v']['value'], 23.2)
        self.assertIsNone(value['h743']['battery_current_a']['value'])
        self.assertIsNone(value['h743']['on_ground']['value'])
        self.assertTrue(value['pi']['api_alive']['value'])

    def test_new_heartbeat_cannot_refresh_frozen_sensor(self):
        self.flight['last_heartbeat_unix'] = 99.9
        self.flight['sensors']['VFR_HUD:0']['field_updated_unix']['groundspeed_mps'] = 95
        self.assertFalse(self.snapshot()['h743']['groundspeed_mps']['fresh'])

    def test_battery_source_cannot_mix_other_component(self):
        self.flight['battery']['source_component_id'] = 2
        self.assertIsNone(self.snapshot()['h743']['battery_voltage_v']['value'])

    def test_field_flag_source_and_nonfinite_are_independent(self):
        row = self.flight['sensors']['VFR_HUD:0']
        row['field_fresh']['groundspeed_mps'] = False
        self.assertIsNone(self.snapshot()['h743']['groundspeed_mps']['value'])
        row['field_fresh']['groundspeed_mps'] = True
        row['source_system_id'] = 2
        self.assertIsNone(self.snapshot()['h743']['groundspeed_mps']['value'])
        row['source_system_id'] = 1
        for invalid in (True, math.nan, math.inf):
            row['values']['groundspeed_mps'] = invalid
            self.assertIsNone(self.snapshot()['h743']['groundspeed_mps']['value'])

    def test_missing_h743_does_not_make_pi_offline_or_invent_disarmed(self):
        self.flight = {'connected': False, 'fresh': False, 'reason': 'no_fresh_heartbeat'}
        value = self.snapshot()
        self.assertFalse(value['h743']['connected']['fresh'])
        self.assertIsNone(value['h743']['armed']['value'])
        self.assertTrue(value['pi']['api_alive']['value'])
        self.assertIn('H743_TELEMETRY_UNAVAILABLE', [item['code'] for item in value['faults']])

    def test_real_ground_evidence_required(self):
        self.flight['ground_state'] = {'message_type': 'EXTENDED_SYS_STATE', 'fresh': True, 'landed_state': 1}
        self.assertFalse(self.snapshot()['h743']['on_ground']['fresh'])
        self.flight['ground_state']['updated_unix'] = 99.5
        self.flight['ground_state'].update(source_system_id=1, source_component_id=1)
        self.assertTrue(self.snapshot()['h743']['on_ground']['value'])
        self.flight['ground_state']['source_system_id'] = 2
        self.assertIsNone(self.snapshot()['h743']['on_ground']['value'])

    def test_position_needs_independently_fresh_3d_fix(self):
        self.flight['sensors']['GLOBAL_POSITION_INT:0'] = record('GLOBAL_POSITION_INT', {'latitude': 40.0, 'longitude': -80.0})
        self.assertIsNone(self.snapshot()['h743']['latitude_deg']['value'])
        self.flight['sensors']['GPS_RAW_INT:0'] = record('GPS_RAW_INT', {'fix_type': 3})
        self.assertEqual(self.snapshot()['h743']['latitude_deg']['value'], 40.0)
        self.flight['sensors']['GPS_RAW_INT:0']['field_updated_unix']['fix_type'] = 90
        self.assertIsNone(self.snapshot()['h743']['latitude_deg']['value'])

    def test_camera_node_does_not_imply_captured_frame(self):
        value = self.snapshot(vision={'fresh': True, 'detections': [{'label': 'person'}]})
        self.assertFalse(value['camera']['fresh'])
        self.assertIsNone(value['camera']['detection_count'])

    def test_bounded_worst_case_all_ranges_rc_messages_services(self):
        for instance in range(8):
            row = record('DISTANCE_SENSOR', {'orientation': 24, 'current_distance': 65535})
            row['instance'] = instance
            self.flight['sensors'][f'DISTANCE_SENSOR:{instance}'] = row
        self.flight['sensors']['RC_CHANNELS:0'] = record('RC_CHANNELS', {f'chan{index}_raw': 65534 for index in range(1, 19)})
        stamp = datetime.fromtimestamp(99, timezone.utc).isoformat()
        self.flight['messages'] = [{'severity': 'warning' * 100, 'text': '\U0001f680' * 10000, 'time_utc': stamp} for _ in range(6)]
        services = {'fresh': True, 'sample_succeeded': True, 'age_ms': 1200, 'units': ['system:orangepi-' + 'x' * 1000] * 100}
        health = {name: {'fresh': False, 'reason': '\U0001f680' * 10000, 'extra': ['x'] * 10000} for name in ('camera', 'rplidar', 'matrix_lidar', 'flight_controller')}
        phone = {'status': 'unavailable', 'extra': ['x' * 10000] * 100}
        vision = {'schema': 1, 'authority': 'observation_only_no_flight_commands', 'status': 'active',
                  'fresh': True, 'captured_unix': 99.5,
                  'detections': [{'class_id': 9999, 'label': '\U0001f680' * 10000, 'confidence': .999999999,
                                  'box': [1.23456789, 2.3456789, 65534.999, 65535]} for _ in range(100)]}
        pi = display.sample_pi()
        value = display.build_snapshot(self.flight, health, phone, now=100, pi=pi, services=services, vision=vision)
        size = len(json.dumps(value, separators=(',', ':')).encode())
        self.assertLessEqual(size, 12288, f'Worst-case wire size {size}')
        self.assertEqual(len(value['rangefinders']), 8)
        self.assertEqual(len(value['rc_channels']['values']), 18)
        self.assertLessEqual(len(value['messages']), 6)
        self.assertTrue(value.get('payload_truncated'))
        self.assertEqual(len(value['pi_service_health']['units']), 8)
        self.assertLessEqual(len(value['camera']['detections']), 4)
        (Path(__file__).parent/'fixtures/display-worst-case.json').write_text(json.dumps(value,separators=(',',':')))
        self.assertNotIn('extra', value['follow_location'])

    def test_independently_timestamped_messages(self):
        self.flight['messages'] = [{'severity': 'warning', 'text': 'GPS unavailable', 'time_utc': datetime.fromtimestamp(99, timezone.utc).isoformat()},
                                   {'severity': 'error', 'text': 'Old message', 'time_utc': datetime.fromtimestamp(1, timezone.utc).isoformat()}]
        value = self.snapshot()
        self.assertEqual(len(value['messages']), 1)
        self.assertEqual(value['messages'][0]['age_ms'], 1000)

    def test_failed_service_sample_is_not_blanket_health_claim(self):
        value = self.snapshot(services={'fresh': True, 'sample_succeeded': True, 'units': ['user:orangepi-ai.service'], 'age_ms': 1200})
        self.assertIn('PI_SERVICE_FAILED', [item['code'] for item in value['faults']])
        value = self.snapshot(services={'fresh': False, 'sample_succeeded': False, 'units': [], 'age_ms': None})
        self.assertIn('PI_SERVICE_CHECK_UNAVAILABLE', [item['code'] for item in value['faults']])

    def test_stale_ai_publication_is_unknown(self):
        value = self.snapshot(performance={'ai_process_active': True}, performance_stamp=90)
        self.assertIsNone(value['pi']['ai_process_active']['value'])

    def test_actual_no_controller_capture_stays_compact(self):
        folder = Path(__file__).resolve().parents[1]
        self.flight = json.loads((folder / 'pi-live-telemetry-flight-132520.json').read_text())['value']
        health = json.loads((folder / 'pi-live-telemetry-status-132520.json').read_text())['value']['sensor_health']
        value = display.build_snapshot(self.flight, health, {'status': 'unavailable'}, now=1792761920, pi={})
        self.assertLess(len(json.dumps(value, separators=(',', ':')).encode()), 12288)
        self.assertIsNone(value['h743']['battery_voltage_v']['value'])


if __name__ == '__main__': unittest.main()


class CpuSamplingTests(unittest.TestCase):
    def setUp(self):
        display._cpu_previous = display._cpu_sample = None

    def test_busy_consumers_preserve_real_sample_age_and_zero(self):
        self.assertFalse(display.cpu_metric(1000, 500, 10)['fresh'])
        self.assertFalse(display.cpu_metric(1100, 600, 10.1)['fresh'])
        first = display.cpu_metric(1300, 800, 10.3)
        self.assertEqual(first['value'], 0)
        self.assertTrue(first['fresh'])
        repeated = display.cpu_metric(1400, 900, 10.4)
        self.assertTrue(repeated['fresh'])
        self.assertGreaterEqual(repeated['age_ms'], 99)
        self.assertFalse(display.cpu_metric(1300, 800, 13)['fresh'])

    def test_counter_reset_clears_sample(self):
        display.cpu_metric(1000, 500, 10)
        self.assertTrue(display.cpu_metric(1300, 600, 10.3)['fresh'])
        self.assertFalse(display.cpu_metric(100, 50, 10.4)['fresh'])

    def test_ten_thousand_overlapping_consumer_samples(self):
        for i in range(10000):
            value = display.cpu_metric(1000 + i * 10, 500 + i * 5, 10 + i * .01)
            if i >= 26:
                self.assertTrue(value['fresh'])
                self.assertEqual(value['value'], 50)
                self.assertLessEqual(value['age_ms'], 260)
