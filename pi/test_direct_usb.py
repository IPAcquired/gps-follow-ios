import json
import time
import unittest

from direct_usb import DirectWire, PAIRED_BUILD

MAC=bytes.fromhex("020000000001")

class FakeScreen:
    def __init__(self):
        self.data=bytearray()
        self.ack=0
        self.mac=MAC
        self.version=PAIRED_BUILD
        self.writes=[]
        self.up=b""
        self.busy=False
    @property
    def in_waiting(self):return len(self.data)
    def read(self,size):
        n=min(size,4)
        out=bytes(self.data[:n]);del self.data[:n]
        return out
    def write(self,packet):
        doc=json.loads(packet)
        if doc["action"]=="wired_status":
            reply=dict(display="Hosyond-E32R35T",firmware=self.version,paired=True,screen_mac=self.mac.hex())
        else:
            self.writes.append((doc["seq"],doc["down_hex"]))
            if doc["seq"] and not self.busy:self.ack=doc["seq"]
            reply=dict(ack=self.ack,busy=self.busy,up_hex=self.up.hex())
        reply["request_id"]=doc["request_id"]
        self.data.extend(b"boot text\n"+json.dumps(reply).encode()+b"\n")
        return len(packet)

class DirectTests(unittest.TestCase):
    def test_exact_pair_and_bidirectional_records(self):
        dev=FakeScreen();link=DirectWire(dev,MAC,lambda:None);link.begin()
        records=[];link.on_record=records.append
        dev.up=b"private uplink"
        link.send(b"private graphics")
        self.assertEqual(records,[dev.up])
        self.assertEqual(bytes.fromhex(dev.writes[-1][1]),b"private graphics")
        link.next_line(time.monotonic()+1)
        self.assertEqual(dev.writes[-1],(0,""))
        link.end()
        with self.assertRaises(ValueError):link.send(b"after close")

    def test_other_screen_rejected_before_content(self):
        dev=FakeScreen();dev.mac=bytes(6)
        with self.assertRaises(PermissionError):DirectWire(dev,MAC,lambda:None).begin()
        self.assertEqual(dev.writes,[])

    def test_reviewed_alert_revision_shares_pairing(self):
        for revision in ("-r2","-r3","-r3.1","-r3.2","-r3.3","-r3.4"):
            dev=FakeScreen();dev.version=PAIRED_BUILD+revision
            DirectWire(dev,MAC,lambda:None).begin()

    def test_primary_route_priority(self):
        dev=FakeScreen();link=DirectWire(dev,MAC,lambda:None);link.begin();dev.busy=True
        dev.up=b"untrusted";records=[];link.on_record=records.append
        self.assertIsNone(link.exchange(1,b"x",time.monotonic()+1))
        self.assertEqual(records,[])

if __name__=="__main__":unittest.main()
