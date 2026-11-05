import unittest
from dataclasses import replace
from desk_model import DeskPlan, audit, RadioEmulator, DeskRadioHost, RadioFailure
from test_uwb_follow import TEST_KEY


def verified_fixture():
    # Deliberate model assumptions, not readings from the user's real boards.
    return DeskPlan(compute_v=5.0, regulator_a=6.0, uart_pins_verified=True,
                    usb_host_and_power_verified=True, reset_wire_verified=True,
                    servo_supply_a=8.0, optional_trick_travel_deg=90.0)


class DeskHardwareTests(unittest.TestCase):
    def test_assumed_correct_wiring_has_no_model_conflicts(self):
        self.assertEqual(audit(verified_fixture()),[])

    def test_actual_unverified_plan_is_not_passed_as_ready(self):
        issues = audit(DeskPlan())
        self.assertIn("compute_output_voltage_unverified",issues)
        self.assertIn("regulator_current_unverified",issues)
        self.assertIn("orange_pi_uart_pinmux_unverified",issues)

    def test_individual_wiring_and_configuration_mistakes(self):
        faults = (
            ({"regulator_input_max_v":25},"regulator_input_overvoltage"),
            ({"compute_v":6},"compute_output_wrong_voltage"),
            ({"regulator_a":2},"compute_power_budget_insufficient"),
            ({"uwb_v":5},"uwb_supply_wrong_voltage"),
            ({"uart_logic_v":5},"uart_logic_overvoltage"),
            ({"servo_rail_shared":True},"servo_compute_rails_must_be_separate"),
            ({"common_ground":False},"no_common_signal_ground"),
            ({"crossed_tx_rx":False},"tx_rx_not_crossed"),
            ({"uwb_baud":9600},"uwb_wrong_baud"),
            ({"lidar_baud":115200},"c1_wrong_baud"),
            ({"tof_transport":"uart"},"tof_uart_bandwidth_overload"),
            ({"uwb_port":"/dev/ttyS1"},"uwb_port_reserved_for_bluetooth"),
            ({"os_target":"Orange Pi Zero 2W H618"},"wrong_orange_pi_os_image"),
        )
        for change, expected in faults:
            with self.subTest(change=change): self.assertIn(expected,audit(replace(verified_fixture(),**change)))

    def test_port_alias_and_two_owners(self):
        plan=verified_fixture()
        plan.owners["uwb"]="FC_USB_BY_ID"
        self.assertIn("two_devices_share_one_port",audit(plan))
        self.assertIn("uwb_device_path_mismatch",audit(plan))

    def test_tof_usb_or_reduced_uart_configuration(self):
        self.assertNotIn("tof_uart_bandwidth_overload",audit(verified_fixture()))
        self.assertNotIn("tof_uart_bandwidth_overload",audit(replace(verified_fixture(),
            tof_transport="uart",tof_baud=921600,tof_width=50,tof_fps=10)))

    def test_invalid_power_ratings_never_pass(self):
        for name in ("regulator_input_max_v","battery_max_v","compute_v","regulator_a"):
            for value in (float("nan"),float("inf"),-1,"5"):
                with self.subTest(name=name,value=value):
                    self.assertTrue(audit(replace(verified_fixture(),**{name:value})))

    def test_invalid_wiring_flags_and_tof_settings_never_pass(self):
        for name,value in (("common_ground","false"),("uart_pins_verified","yes"),
                           ("tof_width",101),("tof_fps",float("nan")),("tof_baud",0)):
            self.assertTrue(audit(replace(verified_fixture(),**{name:value})))

    def test_existing_servo_supply_has_insufficient_stall_budget(self):
        self.assertIn("servo_simultaneous_stall_exceeds_supply",
                      audit(replace(verified_fixture(),servo_supply_a=5.0)))
        self.assertIn("servo_supply_wrong_voltage",audit(replace(verified_fixture(),servo_v=7.0)))

    def test_requested_optional_servo_arc_cannot_be_assumed_supported(self):
        self.assertIn("optional_trick_exceeds_standard_servo_travel",
                      audit(replace(verified_fixture(),optional_trick_travel_deg=270)))


class RadioStartupTests(unittest.TestCase):
    def test_factory_configuration_is_changed_and_read_back(self):
        radio=RadioEmulator()
        host=DeskRadioHost(radio)
        host.start(TEST_KEY,tag=True)
        self.assertTrue(host.ready)
        self.assertFalse(host.reset_asserted)
        self.assertEqual(radio.settings["CPIN"],TEST_KEY)
        self.assertGreater(radio.flash_writes,0)

    def test_repeat_start_does_not_rewrite_flash(self):
        radio=RadioEmulator()
        host=DeskRadioHost(radio)
        host.start(TEST_KEY,tag=True)
        writes=radio.flash_writes
        host.start(TEST_KEY,tag=True)
        for i in range(1000): host.heartbeat(i)
        self.assertEqual(radio.flash_writes,writes)

    def test_all_fragment_sizes(self):
        for size in range(1,49):
            host=DeskRadioHost(RadioEmulator(),fragment_size=size)
            host.start(TEST_KEY,tag=True)
            self.assertTrue(host.ready)

    def test_unplug_swapped_rx_wrong_baud_and_power_loss_timeout(self):
        for powered,link in ((False,True),(True,False)):
            radio=RadioEmulator();radio.powered=powered;radio.link_ok=link
            host=DeskRadioHost(radio)
            with self.assertRaises(RadioFailure): host.start(TEST_KEY,tag=True)
            self.assertFalse(host.ready)
            self.assertTrue(host.reset_asserted)

    def test_delayed_truncated_or_stale_ack_is_not_success(self):
        for response in (b"+OK",b"xxx+OK\r\n",b"+OK-SUFFIX\r\n",b"+READY\r\n+OK\r\n",b"x"*150+b"+OK\r\n"):
            radio=RadioEmulator();radio.reply_override=response
            host=DeskRadioHost(radio)
            with self.assertRaises(RadioFailure): host.start(TEST_KEY,tag=True)
            self.assertTrue(host.reset_asserted)
        host=DeskRadioHost(RadioEmulator(),byte_interval_ms=100)
        with self.assertRaises(RadioFailure): host.start(TEST_KEY,tag=True)

    def test_wrong_readback_never_arms_radio(self):
        for name in ("MODE","CHANNEL","BANDWIDTH","NETWORKID","ADDRESS","CPIN","TAGD"):
            radio=RadioEmulator();radio.bad_readback=name
            host=DeskRadioHost(radio)
            with self.assertRaises(RadioFailure): host.start(TEST_KEY,tag=True)
            self.assertFalse(host.ready)
            self.assertTrue(host.reset_asserted)

    def test_error_then_matching_readback_is_fatal(self):
        radio=RadioEmulator();radio.reply_override=b"+ERR=1\r\n+MODE=0\r\n"
        host=DeskRadioHost(radio,fragment_size=64)
        with self.assertRaises(RadioFailure): host.exchange("AT+MODE?","+MODE=")
        self.assertTrue(host.reset_asserted)

    def test_reset_requires_reprovisioning_and_key_not_in_error(self):
        radio=RadioEmulator();host=DeskRadioHost(radio)
        host.start(TEST_KEY,tag=True);radio.reset()
        host.start(TEST_KEY,tag=True)
        self.assertEqual(radio.settings["CPIN"],TEST_KEY)
        radio.powered=False
        with self.assertRaises(RadioFailure) as error: host.heartbeat(1)
        self.assertNotIn(TEST_KEY,str(error.exception))
        self.assertTrue(host.reset_asserted)

    def test_pair_configuration_and_each_rf_mismatch(self):
        tag=RadioEmulator();anchor=RadioEmulator()
        DeskRadioHost(tag).start(TEST_KEY,tag=True)
        DeskRadioHost(anchor).start(TEST_KEY,tag=False)
        self.assertTrue(anchor.range_response(tag))
        for name in ("CHANNEL","BANDWIDTH","NETWORKID","CPIN","ADDRESS","MODE"):
            value=tag.settings[name];tag.settings[name]="BAD"
            self.assertEqual(anchor.range_response(tag),b"")
            tag.settings[name]=value

if __name__=="__main__": unittest.main()
