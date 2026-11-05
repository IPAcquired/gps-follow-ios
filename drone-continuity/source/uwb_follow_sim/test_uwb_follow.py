import math
import random
import unittest
from dataclasses import replace
from uwb_follow import (
    FollowGate, GateState, RangeSample, VisionSample, TAG_ADDRESS, NETWORK_ID,
    LineFramer, anchor_configuration, anchor_poll_command, counter_payload,
    parse_anchor_line, radio_settings, serial_utilization_hz, validate_aes_key,
)

TEST_KEY = "0123456789ABCDEFFEDCBA9876543210"  # Public fixture; never operating credentials.
AUTHORITY = dict(follow_enabled=True, pilot_override=False, navigation_healthy=True,
                 flight_mode_allowed=True, armed=True, controller_link_healthy=True,
                 obstacle_data_fresh=True, path_clear=True, target_binding_confirmed=True)

def reading(distance, t, seq):
    return RangeSample(TAG_ADDRESS, counter_payload(seq), distance, t, -63)

def camera(t, **kwargs):
    values = dict(target_id=TAG_ADDRESS, bearing_deg=0.0, confidence=.95, received_s=t)
    values.update(kwargs)
    return VisionSample(**values)

class UWBFollowTests(unittest.TestCase):
    def primed(self, distance=7.0, seq=1):
        gate = FollowGate()
        for i, t in enumerate((0.0, .1, .2)):
            self.assertTrue(gate.add_range(reading(distance, t, (seq+i) & 0xFFFFFFFF), t))
        return gate

    def evaluate(self, gate, t=.25, vision=None, **kwargs):
        flags = AUTHORITY | kwargs
        return gate.evaluate(t, camera(t) if vision is None else vision, **flags)

    def no_motion(self, cmd):
        self.assertEqual((cmd.forward_mps, cmd.yaw_rate_dps), (0, 0), cmd)

    def test_documented_distance_and_optional_rssi(self):
        for suffix in ("", ",-61"):
            sample = parse_anchor_line("+ANCHOR_RCV=NATE0001,8,00000003,704 cm"+suffix, 3)
            self.assertEqual(sample.distance_m, 7.04)

    def test_protocol_configuration_and_payload_lengths(self):
        tag = radio_settings(TEST_KEY, tag=True)
        anchor = radio_settings(TEST_KEY, tag=False)
        for key in ("NETWORKID", "CHANNEL", "BANDWIDTH", "CPIN"):
            self.assertEqual(tag[key], anchor[key])
        self.assertEqual(tag["MODE"], "0")
        self.assertEqual(anchor["MODE"], "1")
        self.assertEqual(len(TAG_ADDRESS), 8)
        self.assertEqual(len(NETWORK_ID), 8)
        self.assertEqual(anchor_poll_command(1), "AT+ANCHOR_SEND=NATE0001,8,00000001")
        self.assertIn("AT+CHANNEL=5", anchor_configuration(TEST_KEY))

    def test_key_rejection(self):
        for key in ("0"*32, "F"*31, "F"*33, "g"*32, "1"*31+"\n", None, 32):
            with self.subTest(key_type=type(key).__name__), self.assertRaises(ValueError):
                validate_aes_key(key)

    def test_malformed_packets(self):
        bad = ("garbage", "+ANCHOR_RCV=EVIL0001,8,00000001,400 cm",
               "+ANCHOR_RCV=NATE0001,7,00000001,400 cm",
               "+ANCHOR_RCV=NATE0001,8,NATE0001,400 cm",  # old constant payload rejected
               "+ANCHOR_RCV=NATE0001,8,00000001,0 cm",
               "+ANCHOR_RCV=NATE0001,8,00000001,10001 cm",
               "+ANCHOR_RCV=NATE0001,8,00000001,-1 cm",
               "+ANCHOR_RCV=NATE0001,8,00000001,400 cm,-999",
               "+ANCHOR_RCV=NATE0001,8,00000001,400 cm,1",
               " +ANCHOR_RCV=NATE0001,8,00000001,400 cm",
               "+ANCHOR_RCV=NATE0001,8,00000001,400 cm\x00", "x"*500)
        for line in bad:
            with self.subTest(line=line[:60]), self.assertRaises(ValueError):
                parse_anchor_line(line, 0)

    def test_fragmented_line(self):
        raw = b"+ANCHOR_RCV=NATE0001,8,00000003,700 cm,-63\r\n"
        for split in range(len(raw)+1):
            f = LineFramer()
            self.assertEqual(f.feed(raw[:split])+f.feed(raw[split:]), [raw[:-2].decode()])

    def test_whole_line_ack_not_substring(self):
        f = LineFramer()
        self.assertEqual(f.feed(b"garbage+OK\r\n+OK\r\n"), ["garbage+OK", "+OK"])
        self.assertEqual(f.feed(b"+OK\n"), [])
        self.assertEqual(f.feed(b"+OK"), [])
        self.assertEqual(f.feed(b"\r\n"), ["+OK"])

    def test_overflow_suffix_cannot_become_valid_ack(self):
        f = LineFramer()
        self.assertEqual(f.feed(b"x"*200+b"+OK\r\n+OK\r\n"), ["+OK"])
        self.assertEqual(f.rejected, 1)
        self.assertLessEqual(len(f.buffer), 128)

    def test_binary_noise_and_bounded_buffers(self):
        rng = random.Random(743)
        f = LineFramer()
        for _ in range(1000):
            f.feed(rng.randbytes(rng.randrange(1, 512)))
            self.assertLessEqual(len(f.buffer), 128)
        with self.assertRaises(ValueError): f.feed(b"x"*4097)
        f.feed(b"\r\n")
        self.assertEqual(f.feed(b"+OK\r\n"), ["+OK"])

    def test_direct_range_validation(self):
        fields = dict(distance_m=(math.nan, math.inf, -math.inf, -1, 0, 101, "7", True),
                      received_s=(math.nan, math.inf, -1, .31, "0"),
                      payload=("NATE0001", "0000000G", "1", None),
                      tag=("OTHER001", None), rssi=(-999, 1, "-60"))
        for name, values in fields.items():
            for value in values:
                with self.subTest(field=name, value=value):
                    gate = self.primed()
                    self.assertFalse(gate.add_range(replace(reading(7, .3, 4), **{name:value}), .3))
                    self.no_motion(self.evaluate(gate, .3))

    def test_nominal_bounded_request(self):
        cmd = self.evaluate(self.primed(), vision=camera(.25, bearing_deg=25))
        self.assertEqual(cmd.state, GateState.FOLLOW.value)
        self.assertTrue(0 < cmd.forward_mps <= 1.5)
        self.assertTrue(0 < cmd.yaw_rate_dps <= 25)

    def test_missing_authority_defaults_closed(self):
        cmd = self.primed().evaluate(.25, camera(.25), follow_enabled=True,
            pilot_override=False, navigation_healthy=True, flight_mode_allowed=True)
        self.no_motion(cmd)

    def test_each_authority_condition(self):
        for key in ("navigation_healthy", "flight_mode_allowed", "armed",
                    "controller_link_healthy", "obstacle_data_fresh", "path_clear", "target_binding_confirmed"):
            with self.subTest(key=key):
                self.no_motion(self.evaluate(self.primed(), **{key:False}))
                self.no_motion(self.evaluate(self.primed(), **{key:"true"}))

    def test_spike_and_recovery_need_new_cluster(self):
        gate = self.primed()
        self.assertFalse(gate.add_range(reading(30, .3, 4), .3))
        self.no_motion(self.evaluate(gate, .3))
        for seq, t in ((5,.4), (6,.5)):
            self.assertTrue(gate.add_range(reading(7, t, seq), t))
            self.no_motion(self.evaluate(gate, t))
        gate.add_range(reading(7, .6, 7), .6)
        self.assertEqual(self.evaluate(gate, .6).state, "follow")

    def test_exact_timeout_boundary(self):
        self.no_motion(self.evaluate(self.primed(), .7))
        self.no_motion(self.evaluate(self.primed(), .8))

    def test_gap_discards_old_median(self):
        gate = self.primed(distance=50)
        self.no_motion(self.evaluate(gate, 1))
        for seq, t in ((4,1.1), (5,1.2)):
            gate.add_range(reading(2, t, seq), t)
            self.no_motion(self.evaluate(gate, t))
        gate.add_range(reading(2, 1.3, 6), 1.3)
        self.assertEqual(self.evaluate(gate, 1.3).forward_mps, 0)

    def test_frozen_tag_mcu_does_not_refresh_time(self):
        gate = self.primed()
        for t in (.3,.4,.5,.6,.7,.8):
            self.assertFalse(gate.add_range(reading(7, t, 3), t))
        self.no_motion(self.evaluate(gate, .8))

    def test_counter_wrap(self):
        gate = self.primed(seq=0xFFFFFFFE)
        self.assertEqual(self.evaluate(gate).state, "follow")
        self.assertTrue(gate.add_range(reading(7,.3,1),.3))

    def test_restart_or_replay_latches_off(self):
        gate = self.primed(seq=100)
        self.assertFalse(gate.add_range(reading(7,.3,1),.3))
        for i in range(4): gate.add_range(reading(7,.4+i*.1,2+i),.4+i*.1)
        self.no_motion(self.evaluate(gate,.75))
        self.evaluate(gate,.8,follow_enabled=False)
        for i in range(3): gate.add_range(reading(7,.9+i*.1,1+i),.9+i*.1)
        self.assertEqual(self.evaluate(gate,1.15).state, "follow")

    def test_camera_loss_and_wrong_identity(self):
        self.no_motion(self.evaluate(self.primed(), .35, vision=camera(0)))
        self.no_motion(self.evaluate(self.primed(), vision=camera(.25,target_id="OTHER001")))
        self.no_motion(self.primed().evaluate(.25,None,**AUTHORITY))

    def test_camera_nonfinite_invalid_or_future(self):
        fields = dict(bearing_deg=(math.nan, math.inf, -181, 181, "0"),
                      elevation_deg=(math.nan, 46, -46),
                      confidence=(math.nan, math.inf, -1, .69, 1.01),
                      received_s=(math.nan, math.inf, .26, -.1))
        for name, values in fields.items():
            for value in values:
                with self.subTest(name=name,value=value):
                    self.no_motion(self.evaluate(self.primed(), vision=camera(.25,**{name:value})))

    def test_pilot_override_stays_cancelled_after_release(self):
        gate = self.primed()
        self.assertEqual(self.evaluate(gate,pilot_override=True).state, "pilot")
        self.no_motion(self.evaluate(gate,.3))
        self.evaluate(gate,.4,follow_enabled=False)
        for i in range(3): gate.add_range(reading(7,.5+i*.1,i+10),.5+i*.1)
        self.assertEqual(self.evaluate(gate,.75).state, "follow")

    def test_clock_rollback_or_nonfinite_latches(self):
        for bad in (.1, math.nan, math.inf, -1, "0"):
            gate = self.primed()
            self.evaluate(gate)
            self.no_motion(self.evaluate(gate,bad))
            self.no_motion(self.evaluate(gate,.3))

    def test_close_target_and_rear_target_no_forward(self):
        self.assertEqual(self.evaluate(self.primed(distance=2)).forward_mps, 0)
        for bearing in (-180,-90,-31,31,90,180):
            self.assertEqual(self.evaluate(self.primed(),vision=camera(.25,bearing_deg=bearing)).forward_mps,0)

    def test_slant_range_not_used_as_horizontal_distance(self):
        cmd = self.evaluate(self.primed(distance=7),vision=camera(.25,elevation_deg=45))
        self.assertEqual(cmd.forward_mps, 0)

    def test_empty_open_space_is_not_itself_a_failure(self):
        # The obstacle driver must explicitly declare a fresh, valid clear scan.
        self.assertEqual(self.evaluate(self.primed(),obstacle_data_fresh=True,path_clear=True).state,"follow")
        self.no_motion(self.evaluate(self.primed(),obstacle_data_fresh=False,path_clear=True))

    def test_uart_load_and_invalid_load(self):
        self.assertLess(serial_utilization_hz(), .10)
        for value in (-1,math.nan,math.inf):
            with self.assertRaises(ValueError): serial_utilization_hz(value)

if __name__ == "__main__": unittest.main()
