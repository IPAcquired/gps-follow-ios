import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import flight_guard as fg


class GuardrailTests(unittest.TestCase):
    def test_live_gate_separates_bench_limitations(self):
        events = [
            {"elapsed_s": 10.0, "type": "HEARTBEAT", "data": {"base_mode": 0}},
            {"elapsed_s": 10.0, "type": "GPS_RAW_INT", "data": {"fix_type": 3, "satellites_visible": 20}},
            {"elapsed_s": 10.0, "type": "EKF_STATUS_REPORT", "data": {"flags": 31}},
            *[{"elapsed_s": 10.0, "type": "DISTANCE_SENSOR", "data": {"id": i, "orientation": o}} for i, o in ((2, 25), (10, 0), (12, 2), (16, 6))],
        ]
        gate = fg.assess_live_readiness(events, bench_mode=True)
        self.assertEqual(gate["decision"], "NO-GO")
        self.assertEqual(len(gate["limitations"]), 2)
        self.assertFalse(gate["blockers"])

    def test_live_gate_never_downgrades_compass_blocker(self):
        events = [{"elapsed_s": 10.0, "type": "HEARTBEAT", "data": {"base_mode": 0}}, {"elapsed_s": 10.0, "type": "STATUSTEXT", "data": {"text": "PreArm: Check mag field (z diff:287>200)"}}]
        gate = fg.assess_live_readiness(events, bench_mode=True)
        self.assertTrue(any("mag field" in item for item in gate["blockers"]))

    def test_live_gate_rejects_stale_heartbeat(self):
        events = [{"elapsed_s": 1.0, "type": "HEARTBEAT", "data": {"base_mode": 0}}, {"elapsed_s": 10.0, "type": "SYS_STATUS", "data": {"voltage_battery": 23000}}]
        gate = fg.assess_live_readiness(events)
        self.assertTrue(any("stale" in item for item in gate["blockers"]))

    def test_live_gate_uses_latest_radio_failsafe_state(self):
        events = [
            {"elapsed_s": 9.0, "type": "STATUSTEXT", "data": {"text": "Radio Failsafe - Disarming"}},
            {"elapsed_s": 10.0, "type": "STATUSTEXT", "data": {"text": "Radio Failsafe Cleared"}},
            {"elapsed_s": 10.0, "type": "HEARTBEAT", "data": {"base_mode": 0}},
            {"elapsed_s": 10.0, "type": "RC_CHANNELS", "data": {"chancount": 16, "chan3_raw": 988}},
        ]
        gate = fg.assess_live_readiness(events, bench_mode=True)
        self.assertFalse(any("Radio link" in item for item in gate["blockers"]))

    def test_pid_filter_snapshot_is_bounded(self):
        snapshot = fg.summarize_pid_filter_parameters({"ATC_RAT_RLL_P": {"value": 0.064}, "SERIAL1_PROTOCOL": {"value": 2}})
        self.assertEqual(snapshot["ATC_RAT_RLL_P"], 0.064)
        self.assertNotIn("SERIAL1_PROTOCOL", snapshot)

    def test_live_gate_requires_fresh_gps_and_ekf(self):
        events = [{"elapsed_s": 10.0, "type": "HEARTBEAT", "data": {"base_mode": 0}}]
        gate = fg.assess_live_readiness(events, bench_mode=True)
        self.assertTrue(any("GPS" in item for item in gate["blockers"]))
        self.assertTrue(any("EKF" in item for item in gate["blockers"]))
    def test_protected_names_cover_controller_plumbing(self):
        for name in ("SERIAL0_PROTOCOL", "MAV1_OPTIONS", "FRAME_CLASS", "MOT_PWM_TYPE", "RNGFND1_TYPE", "FS_THR_ENABLE"):
            self.assertTrue(fg.is_protected(name), name)

    def test_proposal_rejects_increase(self):
        proposal = {
            "status": "review_required",
            "confirmation_token": "SAFE",
            "changes": [{"name": "ATC_RAT_RLL_P", "before": 0.1, "target": 0.11}],
        }
        with self.assertRaisesRegex(RuntimeError, "reduction-only"):
            fg.validate_proposal(proposal, "SAFE")

    def test_proposal_rejects_protected_parameter(self):
        proposal = {
            "status": "review_required",
            "confirmation_token": "SAFE",
            "changes": [{"name": "SERIAL0_PROTOCOL", "before": 2, "target": 1.9}],
        }
        with self.assertRaisesRegex(RuntimeError, "Unsafe"):
            fg.validate_proposal(proposal, "SAFE")

    def test_proposal_rejects_more_than_ten_percent(self):
        proposal = {
            "status": "review_required",
            "confirmation_token": "SAFE",
            "changes": [{"name": "ATC_RAT_PIT_D", "before": 0.01, "target": 0.0089}],
        }
        with self.assertRaisesRegex(RuntimeError, "limit"):
            fg.validate_proposal(proposal, "SAFE")

    def test_proposal_rejects_absolute_floor(self):
        proposal = {
            "status": "review_required",
            "confirmation_token": "SAFE",
            "changes": [{"name": "ATC_RAT_PIT_D", "before": 0.00051, "target": 0.00046}],
        }
        with self.assertRaisesRegex(RuntimeError, "bounds"):
            fg.validate_proposal(proposal, "SAFE")

    def test_confirmation_token_required(self):
        proposal = {
            "status": "review_required",
            "confirmation_token": "RIGHT",
            "changes": [{"name": "ATC_RAT_PIT_P", "before": 0.1, "target": 0.09}],
        }
        with self.assertRaisesRegex(RuntimeError, "token"):
            fg.validate_proposal(proposal, "WRONG")

    def test_blocked_report_never_calls_ollama(self):
        report = {"blockers": ["IMU clipping increased by 10."], "warnings": []}
        proposal = {"decision": "Blocked", "choices": {}}
        with mock.patch.object(fg.urllib.request, "urlopen") as urlopen:
            result = fg.ollama_explanation_result(report, proposal, "gemma4:26b", fg.DEFAULT_OLLAMA_URL)
        urlopen.assert_not_called()
        self.assertEqual(result["source"], "deterministic")
        self.assertEqual(result["status"], "skipped_blocked_report")

    def test_ollama_failure_uses_deterministic_fallback(self):
        report = {"blockers": [], "warnings": []}
        proposal = {"decision": "No guarded change.", "choices": {}}
        with mock.patch.object(fg.urllib.request, "urlopen", side_effect=fg.urllib.error.URLError("offline")):
            result = fg.ollama_explanation_result(report, proposal, "gemma4:26b", fg.DEFAULT_OLLAMA_URL)
        self.assertEqual(result["source"], "deterministic")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("deterministic fallback", result["text"].lower())

    def test_model_status_reports_installed_model(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"models": [{"name": "gemma4:26b"}, {"name": "qwen2.5:3b"}]}).encode()

        with mock.patch.object(fg.urllib.request, "urlopen", return_value=Response()):
            result = fg.ollama_model_status(fg.DEFAULT_OLLAMA_URL, "qwen2.5:3b")
        self.assertTrue(result["available"])
        self.assertTrue(result["model_installed"])
        self.assertIn("ready", result["message"].lower())

    def test_successful_advisory_request_disables_thinking_and_excludes_parameters(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"response": "Verified advisory prose."}).encode()

        report = {
            "blockers": [],
            "warnings": [],
            "flight": {"duration_s": 30},
            "parameters_all": {"SERIAL0_PROTOCOL": 2},
        }
        proposal = {"status": "no_change", "decision": "No guarded change.", "changes": []}
        with mock.patch.object(fg.urllib.request, "urlopen", return_value=Response()) as urlopen:
            result = fg.ollama_explanation_result(report, proposal, "gemma4:26b", fg.DEFAULT_OLLAMA_URL)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertFalse(payload["think"])
        self.assertNotIn("SERIAL0_PROTOCOL", payload["prompt"])
        self.assertEqual(result["source"], "ollama")
        self.assertEqual(result["text"], "Verified advisory prose.")

    def test_contradictory_gain_advice_is_discarded(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"response": "Increase gains above the current settings."}).encode()

        report = {"blockers": [], "warnings": [], "flight": {"duration_s": 30}}
        proposal = {
            "status": "review_required",
            "decision": "Reduce roll gains.",
            "changes": [{"name": "ATC_RAT_RLL_P", "before": 0.1, "target": 0.09}],
        }
        with mock.patch.object(fg.urllib.request, "urlopen", return_value=Response()):
            result = fg.ollama_explanation_result(report, proposal, "qwen2.5:3b", fg.DEFAULT_OLLAMA_URL)
        self.assertEqual(result["source"], "deterministic")
        self.assertEqual(result["status"], "rejected_inconsistent")
        self.assertIn("contradicted", result["message"])


if __name__ == "__main__":
    unittest.main()
