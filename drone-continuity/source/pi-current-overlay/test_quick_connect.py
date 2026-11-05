import concurrent.futures
import unittest
from quick_connect import PairingCodes


class CodesTests(unittest.TestCase):
    def setUp(self):
        self.mono, self.wall = [100.0], [1000.0]
        self.codes = PairingCodes(2000, lambda: self.mono[0], lambda: self.wall[0])

    def token(self):
        return self.codes.issue()['url'].split('#join=')[1]

    def test_expiry_uses_monotonic_time(self):
        token = self.token()
        self.wall[0] = 999
        self.mono[0] += 120
        self.assertFalse(self.codes.consume(token))

    def test_refresh_revokes_previous_code(self):
        old = self.token()
        self.mono[0] += 2
        new = self.token()
        self.assertNotEqual(old, new)
        self.assertFalse(self.codes.consume(old))
        self.assertTrue(self.codes.consume(new))

    def test_concurrent_redeem_has_one_winner(self):
        token = self.token()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(self.codes.consume, [token]*32))
        self.assertEqual(sum(result), 1)

    def test_bad_codes_do_not_consume_good_code(self):
        token = self.token()
        for value in (None, {}, [], '', 'a'*42, 'a'*44, '/'*43, '0'*43):
            self.assertFalse(self.codes.consume(value))
        self.assertTrue(self.codes.consume(token))

    def test_issuance_rate_and_owner_expiry(self):
        token = self.token()
        with self.assertRaises(ValueError):
            self.token()
        self.wall[0] = 2000
        self.assertFalse(self.codes.consume(token))
        self.mono[0] += 2
        with self.assertRaises(ValueError):
            self.token()

    def test_restart_invalidates_code(self):
        token = self.token()
        self.assertFalse(PairingCodes(2000,lambda:100,lambda:1000).consume(token))


if __name__ == '__main__':
    unittest.main()
