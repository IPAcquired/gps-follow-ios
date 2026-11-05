import pathlib
import unittest


PATCH = (pathlib.Path(__file__).resolve().parent /
         "arducopter-4.7.1-directional-adaptive-margin.patch").read_text(encoding="utf-8")
ADDED = "\n".join(line[1:] for line in PATCH.splitlines()
                  if line.startswith("+") and not line.startswith("+++"))


class FirmwarePatchStructure(unittest.TestCase):
    def test_never_mutates_or_saves_global_margin(self):
        self.assertNotIn("_margin_m.set", PATCH)
        self.assertNotIn("set_and_save", PATCH)

    def test_feature_defaults_disabled(self):
        self.assertIn('AP_GROUPINFO("ADAP_EN", 12, AC_Avoid, _adaptive_enable, 0)', PATCH)

    def test_stop_projection_uses_original_velocity(self):
        self.assertIn("stop_projection_speed_cms = safe_vel_orig_neu_cms.length()", ADDED)
        self.assertIn("stopping_point_plus_margin_neu_cm = safe_vel_orig_neu_cms", ADDED)
        self.assertNotIn("stopping_point_plus_margin_neu_cm = safe_vel_neu_cms", ADDED)

    def test_adaptive_effect_is_horizontal_and_guarded(self):
        self.assertIn("if (_adaptive_latched && horizontal_obstacle)", PATCH)
        self.assertIn("fabsf(obstacle_unit.z) < 0.15f", PATCH)

    def test_low_height_requires_fresh_downward_range(self):
        self.assertIn("_proximity.get_fresh_rangefinder_alt(down_alt_m)", PATCH)
        self.assertNotIn("_ahrs.get_hagl", ADDED)
        self.assertIn("actual backend packet timestamp", PATCH)
        self.assertIn("rangefinder.last_reading_ms(ROTATION_PITCH_270)", PATCH)
        self.assertIn("last_downward_reading_ms", PATCH)

    def test_default_off_preserves_stock_ground_suppression_freshness(self):
        self.assertIn("last_downward_update_ms = AP_HAL::millis()", PATCH)
        self.assertIn("AP_HAL::millis() - _rangefinder_state.last_downward_reading_ms", PATCH)
        self.assertIn("last_downward_update_ms;", PATCH)
        self.assertIn("bool get_rangefinder_alt(float &alt_m) const;", PATCH)
        self.assertIn("bool get_fresh_rangefinder_alt(float &alt_m) const;", PATCH)

    def test_enable_and_state_transitions_are_guarded(self):
        self.assertIn("void AC_Avoid::init()", PATCH)
        self.assertIn("avoid.init()", PATCH)
        self.assertIn("@RebootRequired: True", PATCH)
        self.assertIn("_adaptive_latched = (_adaptive_enable != 0)", PATCH)
        self.assertIn("reset_adaptive_state()", PATCH)
        self.assertIn("(adaptive_now_ms - _adaptive_last_call_ms) > 1000U", PATCH)
        self.assertEqual(ADDED.count("_adaptive_latched = (_adaptive_enable != 0)"), 1)

    def test_parameters_are_bounded_before_unit_conversion(self):
        self.assertIn("constrain_float(isfinite(float(_adaptive_reaction_s))", PATCH)
        self.assertIn("0.0f, 1.0f", PATCH)
        self.assertIn("0.0f, 2.0f", PATCH)
        self.assertIn("0.0f, 0.5f", PATCH)
        self.assertIn("0.2f, 10.0f", PATCH)

    def test_velocity_health_and_backaway_scope(self):
        self.assertIn("filter_status.flags.horiz_vel", PATCH)
        self.assertIn("filter_status.flags.attitude", PATCH)
        self.assertIn("dist_to_boundary_cm - base_margin_cm", PATCH)
        self.assertNotIn("dist_to_boundary_cm - margin_cm", ADDED)

    def test_native_stopping_distance_is_not_duplicated(self):
        self.assertEqual(ADDED.count("get_stopping_distance(kP, accel_cmss"), 1)
        self.assertNotIn("sq(closing_speed", ADDED)


if __name__ == "__main__":
    unittest.main()
