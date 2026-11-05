import math
import unittest

from model import Config, SectorState, update_obstacle


class DirectionalAdaptiveMargin(unittest.TestCase):
    def run_case(self, velocity, direction, **kw):
        return update_obstacle(base=1.0, actual_body_xy=velocity,
                               obstacle_unit_xy=direction, enabled=True, **kw)

    def test_disabled_is_bit_identical_baseline(self):
        for v in ((0, 0), (3, 0), (0, -2), (float("nan"), 0)):
            value, _, status, _ = update_obstacle(
                base=1.0, actual_body_xy=v, obstacle_unit_xy=(1, 0), enabled=False)
            self.assertEqual((value, status), (1.0, "stock"))

    def test_projection_front_right_left_and_retreat(self):
        self.assertAlmostEqual(self.run_case((2, 0), (1, 0))[0], 1.7)
        self.assertAlmostEqual(self.run_case((0, 2), (0, 1))[0], 1.7)
        self.assertAlmostEqual(self.run_case((0, -2), (0, -1))[0], 1.7)
        self.assertEqual(self.run_case((-2, 0), (1, 0))[0], 1.0)

    def test_directional_not_global(self):
        self.assertEqual(self.run_case((2, 0), (0, 1))[0], 1.0)
        self.assertGreater(self.run_case((2, 0), (1, 0))[0], 1.0)

    def test_diagonal_and_yaw_equivalent_projection(self):
        s45 = math.sqrt(0.5)
        self.assertAlmostEqual(self.run_case((2, 2), (s45, s45))[1], 2 * math.sqrt(2))
        self.assertAlmostEqual(self.run_case((2, 0), (1, 0))[0], self.run_case((0, 2), (0, 1))[0])

    def test_cap_and_exact_speed_table(self):
        for speed, expected in ((0, 1), (0.5, 1.175), (1, 1.35), (2, 1.7), (3, 2.0), (6, 2.0)):
            self.assertAlmostEqual(self.run_case((speed, 0), (1, 0))[0], expected)

    def test_invalid_velocity_immediately_uses_cap(self):
        value, _, status, _ = self.run_case((float("nan"), 0), (1, 0), velocity_valid=False)
        self.assertEqual((value, status), (2.0, "velocity-fallback"))

    def test_nonfinite_and_extreme_parameters_are_bounded(self):
        cfg = Config(reaction_time=float("inf"), extra_cap=1e38,
                     low_height_add=1e38, low_height_on=float("nan"),
                     low_height_off=-1e38)
        value, _, _, _ = self.run_case((10, 0), (1, 0), hagl=0.5, cfg=cfg)
        self.assertEqual(value, 3.5)

    def test_growth_immediate_decay_limited_and_hysteretic(self):
        state = SectorState()
        high, _, _, state = self.run_case((3, 0), (1, 0), state=state)
        self.assertEqual(high, 2.0)
        lower, _, _, state = self.run_case((0, 0), (1, 0), state=state, dt=0.1)
        self.assertAlmostEqual(lower, 1.95)
        state.extra = 0.30
        held, _, _, _ = self.run_case((0.8, 0), (1, 0), state=state, dt=0.1)
        self.assertAlmostEqual(held, 1.30)

    def test_long_gap_clears_stale_extra_at_decay_limit(self):
        state = SectorState(extra=1.0)
        value, _, _, state = self.run_case((0, 0), (1, 0), state=state, dt=2.0)
        self.assertEqual(value, 1.0)
        self.assertEqual(state.extra, 0.0)

    def test_low_height_hysteresis_horizontal_only(self):
        state = SectorState()
        low, _, _, state = self.run_case((0, 0), (1, 0), hagl=1.4, state=state)
        self.assertEqual(low, 1.15)
        still, _, _, state = self.run_case((0, 0), (1, 0), hagl=1.6, state=state)
        self.assertEqual(still, 1.15)
        released, _, _, state = self.run_case((0, 0), (1, 0), hagl=1.9, state=state)
        self.assertEqual(released, 1.0)
        vertical, _, _, _ = self.run_case((2, 0), (1, 0), hagl=1.0, horizontal=False)
        self.assertEqual(vertical, 1.0)

    def test_invalid_height_suppresses_only_height_extra(self):
        value, _, _, _ = self.run_case((2, 0), (1, 0), hagl=None)
        self.assertAlmostEqual(value, 1.7)

    def test_fresh_obstacles_only_and_no_rear_claim(self):
        front, _, _, _ = self.run_case((-3, 0), (1, 0))
        self.assertEqual(front, 1.0)

    def test_disabled_obstacle_order_does_not_change_margin(self):
        obstacles = [(1, 0), (0, 1), (-1, 0)]
        forward = [update_obstacle(base=1.0, actual_body_xy=(2, 1),
                                   obstacle_unit_xy=o, enabled=False)[0] for o in obstacles]
        reverse = [update_obstacle(base=1.0, actual_body_xy=(2, 1),
                                   obstacle_unit_xy=o, enabled=False)[0] for o in reversed(obstacles)]
        self.assertEqual(forward, [1.0, 1.0, 1.0])
        self.assertEqual(reverse, [1.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
