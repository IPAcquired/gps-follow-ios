import json
import unittest
from unittest.mock import Mock,patch
from direct_usb import DirectWire, DirectTimeout, _rate_cooldown
from paired_wire import LocalBack, SecureSession


class PollPort:
    port="/dev/ttyUSB0"
    def __init__(self,responses):
        self.responses=iter(responses)
        self.now=20.
        self.buffer=bytearray()
        self.sent=[]
    @property
    def in_waiting(self):return len(self.buffer)
    def read(self,n):
        if not self.buffer:self.now+=.005
        data=bytes(self.buffer[:n]);del self.buffer[:n]
        return data
    def write(self,b):
        obj=json.loads(b);self.sent.append(obj)
        response=next(self.responses)
        if response is not None:
            if len(self.sent)>1:
                # The first request's late response must not be consumed as the retry.
                late=dict(request_id=self.sent[0]["request_id"],busy=False,ack=3,up_hex="abcd")
                self.buffer.extend(json.dumps(late).encode()+b"\n")
            result=dict(request_id=obj["request_id"],busy=False,ack=3,up_hex=response)
            self.buffer.extend(json.dumps(result).encode()+b"\n")
        return len(b)


class IdlePollTests(unittest.TestCase):
    def setUp(self):
        _rate_cooldown.clear()

    def run_port(self,responses,operation):
        port=PollPort(responses)
        wire=DirectWire(port,b"123456",lambda:None,max_baud=921600)
        wire.baud=921600;wire.active=True
        with patch("direct_usb.time.monotonic",side_effect=lambda:port.now):
            operation(wire,port)
        return wire,port

    def test_first_loss_recovers_without_demotion_or_renewing_proof(self):
        def probe(wire,port):
            channel=Mock()
            channel.unwrap.return_value=None
            session=SecureSession(wire,channel)
            proof=session.last_proof
            wire.next_line(port.now+1)
            self.assertEqual(session.last_proof,proof)
            self.assertEqual(session.ack,0)
            channel.unwrap.assert_called_once_with(b"\x12\x34")
            self.assertNotIn((wire.route,wire.baud),_rate_cooldown)
        _,port=self.run_port([None,"1234"],probe)
        self.assertEqual([(r["seq"],r["down_hex"]) for r in port.sent],[(0,""),(0,"")])
        self.assertNotEqual(port.sent[0]["request_id"],port.sent[1]["request_id"])
        self.assertLess(port.now-20,.86)

    def test_two_losses_fail_within_total_budget_and_demote(self):
        def probe(wire,port):
            with self.assertRaises(DirectTimeout):wire.next_line(port.now+1)
            self.assertIn((wire.route,wire.baud),_rate_cooldown)
        _,port=self.run_port([None,None],probe)
        self.assertEqual(len(port.sent),2)
        self.assertGreaterEqual(port.now-20,.85)
        self.assertLess(port.now-20,.86)

    def test_data_timeout_never_replayed(self):
        def probe(wire,port):
            with self.assertRaises(DirectTimeout):wire.send(b"protected application record",.45)
            self.assertIn((wire.route,wire.baud),_rate_cooldown)
        _,port=self.run_port([None],probe)
        self.assertEqual(len(port.sent),1)
        self.assertNotEqual(port.sent[0]["seq"],0)

    def test_back_on_second_poll_stops_immediately(self):
        def probe(wire,port):
            wire.on_record=Mock(side_effect=LocalBack("Back"))
            with self.assertRaises(LocalBack):wire.next_line(port.now+1)
            wire.on_record.assert_called_once_with(b"\xff")
            self.assertFalse(_rate_cooldown)
        _,port=self.run_port([None,"ff"],probe)
        self.assertEqual(len(port.sent),2)
