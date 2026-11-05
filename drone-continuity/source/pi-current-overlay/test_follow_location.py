import copy
import math
import unittest
from unittest.mock import patch
from follow_location import PhoneLocationStore


class PhonePositionTests(unittest.TestCase):
    def setUp(self):
        self.store = PhoneLocationStore()
        self.point = {'source': 'phone_gps', 'source_epoch': 'ab' * 16, 'seq': 1,
                      'age_ms': 500, 'lat': 41.8, 'lon': -87.6, 'accuracy_m': 4.5}

    def test_fresh_target_is_not_drone_gps(self):
        value = self.store.accept(self.point)
        self.assertEqual(value['status'], 'fresh')
        self.assertFalse(value['position_is_drone_gps'])
        self.assertFalse(value['mavlink_transmit'])
        self.assertEqual(value['authority'], 'advisory_only')

    def test_ttl_counts_reported_age_and_clears_coordinates(self):
        with patch('follow_location.time.monotonic', return_value=10):
            self.store.accept(self.point)
        with patch('follow_location.time.monotonic', return_value=12.6):
            value = self.store.snapshot()
        self.assertEqual(value['status'], 'stale')
        self.assertNotIn('lat', value)
        self.assertIsNone(self.store.point)

    def test_duplicate_order_and_retired_epoch(self):
        self.store.accept(self.point)
        with self.assertRaises(ValueError): self.store.accept(self.point)
        second = {**self.point, 'source_epoch': 'cd' * 16, 'seq': 2}
        self.store.accept(second)
        with self.assertRaises(ValueError): self.store.accept({**self.point, 'seq': 10})

    def test_stop_is_immediate_and_ordered(self):
        self.store.accept(self.point)
        value = self.store.accept({'source': 'phone_gps', 'source_epoch': self.point['source_epoch'], 'seq': 2, 'stop': True})
        self.assertEqual(value['status'], 'stopped')
        self.assertIsNone(self.store.point)
        with self.assertRaises(ValueError): self.store.accept(self.point)

    def test_bad_numeric_types_ranges_freshness_and_extra_fields(self):
        invalid = [('lat', True), ('lat', 91), ('lon', -181), ('lat', math.nan),
                   ('accuracy_m', 0), ('accuracy_m', 31), ('age_ms', 2501),
                   ('age_ms', -1), ('age_ms', 0.5), ('seq', True), ('seq', 0),
                   ('seq', 4294967295), ('source_epoch', 'not-an-epoch'), ('source', 'drone_gps')]
        for key, value in invalid:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.store.accept({**self.point, key: value})
        with self.assertRaises(ValueError): self.store.accept({**self.point, 'mode': 'FOLLOW'})
        self.assertEqual(self.store.snapshot()['status'], 'unavailable')


if __name__ == '__main__': unittest.main()
