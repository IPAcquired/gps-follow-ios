import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from monitor_patch import patched, BASE
from install import install,service_setup,ANALYZER
from onboard_postflight import ACK, CLOSE, CLIENT_COMP, CLIENT_SYS, Collection, FTP, HEADER, LIST, OPEN_RO, READ, Request
from postflight_store import Deferred, Intake, mounted
from postflight_summary import summarize


def dataflash(extra=0):
    def fmt(typ,length,name,format_,cols):
        return b"\xa3\x95\x80"+struct.pack("<BB4s16s64s",typ,length,name,format_,cols)
    data=fmt(128,89,b"FMT",b"BBnNZ",b"Type,Length,Name,Format,Columns")
    data+=fmt(129,17,b"VER",b"QHBBBB",b"TimeUS,APJ,BT,BU,Maj,Min")
    data+=fmt(130,12,b"TEST",b"QB",b"TimeUS,Value")
    data+=b"\xa3\x95\x81"+struct.pack("<QHBBBB",100,1229,10,2,4,7)
    for i in range(20+extra):data+=b"\xa3\x95\x82"+struct.pack("<QB",i*1000,i%256)
    return data


class Message:
    def __init__(self,kind,source=(1,1),**values):
        self.kind=kind;self.source=source
        self.__dict__.update(values)
    def get_type(self):return self.kind
    def get_srcSystem(self):return self.source[0]
    def get_srcComponent(self):return self.source[1]


class Writer:
    def __init__(self):self.commands=[];self.files=[]
    def command_long_send(self,*args):self.commands.append(args)
    def file_transfer_protocol_send(self,*args):self.files.append(args)


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.store=Intake(self.home)
    def put(self,data,final):
        return self.store.copy("controller","1.BIN",len(data),[data],lambda:True,final)
    def test_content_dedup_current_and_closed(self):
        one=self.put(dataflash(),False);two=self.put(dataflash(),True)
        self.assertFalse(one["queued"]);self.assertTrue(two["queued"])
        self.put(dataflash(),True)
        self.assertEqual(len(list(self.store.inbox.iterdir())),1)
        self.assertEqual(len(list(self.store.snapshots.iterdir())),1)
        with self.assertRaisesRegex(Deferred,"grew_manual"):self.put(dataflash(3),True)
        self.assertEqual(len(list(self.store.inbox.iterdir())),1)
    def test_invalid_or_incomplete(self):
        with self.assertRaises(Deferred):self.put(b"bad",True)
        with self.assertRaises(Deferred):self.store.copy("x","1.BIN",40,[b"ab"],lambda:True,False)
        with self.assertRaises(Deferred):self.store.copy("x","1.BIN",4,[b"abcd"],lambda:False,True)
        with self.assertRaises(Deferred):mounted(self.store,self.home/"APM/LOGS","fixture")
        self.assertFalse(list(self.store.inbox.iterdir()))
        self.assertFalse(list(self.store.snapshots.iterdir()))
    def test_actual_parser(self):
        import os
        if "FIELD_ANALYZER" not in os.environ:self.skipTest("set actual analyzer path")
        entry=self.put(dataflash(),False)
        result=summarize(self.home,entry["sha256"],Path(os.environ["FIELD_ANALYZER"]))
        self.assertEqual(result["message_types"]["TEST"],20)
        self.assertTrue(result["controller_group"].endswith("incomplete-version"))
        self.assertEqual(summarize(self.home,entry["sha256"],Path("absent")),result)
        self.assertTrue((self.store.root/"latest-analysis.json").is_file())
        self.assertFalse(list(self.store.inbox.iterdir()))
    def test_install_rollback(self):
        import os
        if "FIELD_MONITOR" not in os.environ:self.skipTest("set original monitor path")
        dest=self.home/"usr/local/bin/orangepi-mavlink-monitor"
        dest.parent.mkdir(parents=True)
        shutil.copy2(os.environ["FIELD_MONITOR"],dest)
        self.assertEqual(install("check",self.home),"stock")
        self.assertEqual(install("activate",self.home),"active")
        text=dest.read_text()
        self.assertIn('device == "/dev/h743" and Path(device).resolve() == Path("/dev/ttyS0")',text)
        self.assertIn("PC bridge is receive-only",text)
        self.assertEqual(install("activate",self.home),"active")
        self.assertEqual(install("rollback",self.home),"stock")
        self.assertEqual(hashlib.sha256(dest.read_bytes()).hexdigest(),BASE)
        dest.write_bytes(b"local modification")
        with self.assertRaises(ValueError):install("activate",self.home)

    def test_private_sandbox_install(self):
        import os
        if "FIELD_MONITOR" not in os.environ or "FIELD_ANALYZER" not in os.environ:self.skipTest("set fixture paths")
        root=self.home/"system"
        monitor=root/"usr/local/bin/orangepi-mavlink-monitor"
        monitor.parent.mkdir(parents=True)
        shutil.copy2(os.environ["FIELD_MONITOR"],monitor)
        user=self.home/"user"
        (user/"flight-data/inbox").mkdir(mode=0o700,parents=True)
        (user/"flight-data").chmod(0o700)
        (user/"bin").mkdir()
        for name in ANALYZER:shutil.copy2(Path(os.environ["FIELD_ANALYZER"]).parent/name,user/"bin"/name)
        self.assertEqual(service_setup("activate",root,user,os.getuid(),os.getgid()),"active")
        cfg=next((root/"etc").rglob("*.conf"))
        self.assertEqual(len([l for l in cfg.read_text().splitlines() if l.startswith("BindPaths=")]),2)
        self.assertNotIn(str(user/"bin"),cfg.read_text())
        self.assertEqual(service_setup("rollback",root,user,os.getuid(),os.getgid()),"stock")
        self.assertFalse(cfg.exists())

    def test_real_monitor_publication_and_legacy_guard(self):
        import time
        if "FIELD_MONITOR" not in os.environ:self.skipTest("set monitor path")
        api={"__name__":"test_monitor"}
        exec(patched(Path(os.environ["FIELD_MONITOR"]).read_bytes()),api)
        at=[10.0];waits=[];published=[]
        stream=SimpleNamespace()
        values=iter([("HB",.005),("HB",.015),(None,.09),(None,.5)])
        def receive(blocking,timeout):
            waits.append(timeout)
            data,delta=next(values)
            at[0]+=delta
            return Message("HEARTBEAT") if data else None
        stream.recv_match=receive
        stream.close=lambda:None
        def record(s):published.append((at[0],s.get("authority"),s.get("telemetry_provenance")))
        with mock.patch.dict(api,{"ReadOnlyPCPipe":lambda dev:stream,
                                  "update_message":lambda s,m:True,"validate_config":lambda x:x,
                                  "atomic_json":record}),mock.patch.object(time,"monotonic",lambda:at[0]):
            with self.assertRaises(StopIteration):api["monitor"]("/run/orangepi-mavlink/pc-h743.fifo",115200,7)
        self.assertLessEqual(waits[2],.101)
        self.assertEqual(waits[3],.5)
        self.assertTrue(all(authority=="read_only_no_mavlink_transmit" for _,authority,_ in published))
        self.assertEqual(published[-1][2],"observed_from_matching_controller")
        if "FIELD_AI_GUARD" in os.environ:
            import runpy
            guard=runpy.run_path(os.environ["FIELD_AI_GUARD"])["telemetry"]
            t=time.time();source={"system_id":1,"component_id":1}
            data=dict(updated_unix=t,heartbeat_updated_unix=t,schema=1,connected=True,armed=False,
                      transport="/dev/h743",h743_source=source,expected_source=source,
                      authority="read_only_no_mavlink_transmit")
            with mock.patch.dict(guard.__globals__,{"read_file":lambda *a:json.dumps(data).encode()}):
                self.assertTrue(guard()["matched_controller"])
                data["authority"]="read_only_postflight_file_queries"
                self.assertFalse(guard()["matched_controller"])


class TransportTest(unittest.TestCase):
    def test_disarmed_identity_ground_constraints(self):
        at=[10.];writer=Writer();c=Collection(Path("/unused"),(1,1),writer,lambda:at[0],False)
        hb=lambda armed,src=(1,1):Message("HEARTBEAT",src,autopilot=3,type=2,system_status=3,base_mode=128 if armed else 0)
        ground=lambda pos:Message("EXTENDED_SYS_STATE",landed_state=pos)
        for i in range(8):
            at[0]+=1;c.observe(hb(True),{})
        self.assertFalse(writer.commands)
        for i in range(20):
            at[0]+=1;c.observe(hb(False),{})
        self.assertEqual(len(writer.commands),3)
        self.assertTrue(all(x==(1,1,512,0,245,0,0,0,0,0,0) for x in writer.commands))
        self.assertFalse(c.busy)
        c.observe(ground(2),{});self.assertFalse(c.busy)
        c.observe(ground(1),{});self.assertTrue(c.busy)
        e=c.generation;c.tx.put((e,Request(10,LIST,data=b"/APM/LOGS")))
        c.observe(None,{})
        self.assertEqual(len(writer.files),1)
        c.tx.put((e,Request(12,LIST,data=b"/APM/LOGS")))
        c.observe(hb(True),{})
        self.assertFalse(c.busy);self.assertNotEqual(c.generation,e)
        self.assertEqual(len(writer.files),1)
        for i in range(20):
            at[0]+=1;c.observe(hb(False),{});c.observe(hb(False,(4,1)),{});c.observe(ground(1),{})
        self.assertFalse(c.safe(at[0]))
        self.assertEqual(len(writer.files),1)
    def test_only_approved_ops_names(self):
        for req in [Request(1,op) for op in (2,6,7,8,9,10,11,12,13,14,15)]+[
                Request(1,OPEN_RO,data=b"/APM/LOGS/../hello"),Request(1,LIST,data=b"/PARAM"),
                Request(1,LIST,offset=1,data=b"/"),
                Request(1,READ,0,0,240)]:
            with self.assertRaises(Deferred):req.packet()
    def test_timeout_retries_and_ack_matching(self):
        attempts=[]
        def peer(r):
            attempts.append(r.seq)
            seq=r.seq if len(attempts)==1 else (r.seq+1)&65535
            sid=13 if len(attempts)<3 else 7
            return HEADER.pack(seq,sid,ACK,1,r.op,0,0,r.offset)+b"x"
        ftp=FTP(peer)
        self.assertEqual(ftp.request(READ,7,90,1),(7,b"x"))
        self.assertEqual(len(set(attempts)),1)
        self.assertEqual(len(attempts),3)
        with self.assertRaises(Deferred):FTP(lambda _:None).listing()


if __name__=="__main__":unittest.main()
