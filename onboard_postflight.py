"""Postflight MAVFTP client on the existing native telemetry connection."""
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import random
import re
import struct
import subprocess
import threading
import time

from postflight_store import Deferred, Intake, LIMIT, NAME, publish_json


HEADER = struct.Struct("<H6BI")
LIST, OPEN_RO, READ, CLOSE = 3, 4, 5, 1
ACK, NAK = 128, 129
LOG_DIR = "/APM/LOGS"
LAST = "LASTLOG.TXT"
CLIENT_SYS, CLIENT_COMP = 246, 191


@dataclass(frozen=True)
class Request:
    seq: int
    op: int
    session: int = 0
    offset: int = 0
    size: int = 0
    data: bytes = b""

    def packet(self):
        if self.op == LIST:
            permitted = (self.session==0 and ((self.data==LOG_DIR.encode() and 0<=self.offset<=65536)
                         or (self.data in (b"/",b"/APM") and self.offset==0)))
        elif self.op == OPEN_RO:
            permitted = (self.session==0 and self.offset==0 and
                         re.fullmatch(rb"/APM/LOGS/(?:[0-9]{1,10}\.[Bb][Ii][Nn]|LASTLOG\.TXT)",self.data))
        elif self.op == READ:
            permitted = not self.data and 1<=self.size<=239 and 0<=self.offset<LIMIT
        else:
            permitted = self.op==CLOSE and not self.data and self.offset==0 and self.size==0
        if not permitted:
            raise Deferred("unapproved_file_operation")
        size=self.size if self.op==READ else len(self.data)
        return (HEADER.pack(self.seq,self.session,self.op,size,0,0,0,self.offset)+self.data).ljust(251,b"\0")


class FTP:
    def __init__(self, exchange):
        self.exchange=exchange
        self.seq=random.SystemRandom().randrange(0,65536)

    def request(self, op, session=0, offset=0, size=0, data=b"", eof=False):
        req=Request(self.seq,op,session,offset,size,data)
        req.packet()
        for _ in range(3):
            reply=self.exchange(req)
            if reply is None:continue
            if len(reply)<12:continue
            seq,sid,code,n,origin,burst,pad,pos=HEADER.unpack_from(reply)
            if seq!=(req.seq+1)&65535 or origin!=op or n>239 or n>len(reply)-12:continue
            if op in (READ,CLOSE) and sid!=session:continue
            if code==ACK and op in (READ,LIST) and pos!=offset:continue
            self.seq=(req.seq+2)&65535
            body=bytes(reply[12:12+n])
            if code==NAK and eof and body[:1]==b"\x06":return sid,b""
            if code==NAK:
                label={LIST:"list",OPEN_RO:"open",READ:"read",CLOSE:"close"}[op]
                detail="_".join(str(n) for n in body[:2]) or "empty"
                raise Deferred("file_service_declined_"+label+"_"+detail)
            if code!=ACK:raise Deferred("invalid_file_service_reply")
            return sid,body
        raise Deferred("file_service_timeout_or_bad_reply")

    def listing(self):
        offset=0;files={}
        while offset<=65536:
            _,raw=self.request(LIST,offset=offset,data=LOG_DIR.encode(),eof=True)
            if not raw:return files
            entries=raw.rstrip(b"\0").split(b"\0")
            for entry in entries:
                m=re.fullmatch(rb"F([0-9]{1,10}\.[Bb][Ii][Nn])\t([0-9]{1,10})",entry)
                if m:
                    name=m[1].decode()
                    if name in files:raise Deferred("duplicate_directory_entry")
                    files[name]=int(m[2])
            offset+=len(entries)
        raise Deferred("directory_limit")

    def stream(self,name,expected):
        sid,raw=self.request(OPEN_RO,data=(LOG_DIR+"/"+name).encode())
        try:
            if len(raw)!=4:raise Deferred("invalid_open_receipt")
            length=int.from_bytes(raw,"little")
            if not 0<length<=expected or (name!=LAST and length!=expected):
                raise Deferred("file_changed_before_read")
            ofs=0
            while ofs<length:
                wanted=min(239,length-ofs)
                _,chunk=self.request(READ,sid,ofs,wanted)
                if not 0<len(chunk)<=wanted:raise Deferred("short_or_invalid_file")
                ofs+=len(chunk)
                yield chunk
        finally:
            self.request(CLOSE,sid)

    def newest(self):
        raw=b"".join(self.stream(LAST,32)).strip(b" \t\r\n\0")
        index=re.fullmatch(rb"([0-9]{1,10})D?",raw.splitlines()[0] if raw else b"")
        if not index:raise Deferred("invalid_current_log_index")
        return int(index[1])

    def size(self,name):
        sid,raw=self.request(OPEN_RO,data=(LOG_DIR+"/"+name).encode())
        try:
            if len(raw)!=4:raise Deferred("invalid_open_receipt")
            return int.from_bytes(raw,"little")
        finally:self.request(CLOSE,sid)

    def directory_hint(self,path,label):
        try:
            _,raw=self.request(LIST,data=path,eof=True)
        except Deferred as exc:
            if not str(exc).startswith("file_service_declined_list_"):raise
            return str(exc)
        return "present" if b"D"+label in raw.split(b"\0") else "absent_from_first_page"


class Collection:
    def __init__(self,home,expected,writer,clock=time.monotonic,start=True):
        self.home,self.target,self.writer,self.clock=home,expected,writer,clock
        self.hb=self.ground=self.blocked_to=self.parked_since=0.
        self.armed=None;self.landed=False;self.parked=False
        self.last_query=-100.;self.last_tx=-100.;self.flight=None;self.generation=0
        self.query_count=0;self.ftp_count=0;self.tries=0
        self.next_run=0.;self.next_ground_query=0.;self.want=True
        self.failures=0;self.diagnostics={}
        self.enabled=expected[0]!=CLIENT_SYS
        self.stop=threading.Event();self.wake=threading.Event()
        self.tx=queue.Queue(1);self.rx=queue.Queue(8)
        self.current=None;self.busy=False;self.last_state="waiting_for_parked_source"
        self.thread=None
        self.holds=(Path("/run/orangepi-flight-active"),Path("/run/orangepi-maintenance-active"),
                    home/"flight-data/acquisition/paused")
        if start:
            self.thread=threading.Thread(target=self.worker,daemon=True)
            self.thread.start()

    def safe(self,now):
        return (self.enabled and self.parked and self.landed and self.hb>0 and 0<=now-self.hb<2
                and self.ground>0 and 0<=now-self.ground<4 and now>=self.blocked_to
                and now-self.parked_since>=5 and not self.stop.is_set() and not self.held())

    def held(self):
        return any(path.exists() for path in self.holds)

    def observe(self,msg,state):
        now=self.clock()
        if msg is not None:
            kind=msg.get_type();source=(msg.get_srcSystem(),msg.get_srcComponent())
            if kind=="HEARTBEAT" and msg.autopilot==3 and msg.type!=6:
                if source!=self.target and source[1]==self.target[1]:
                    self.blocked_to=now+15
                elif source==self.target:
                    was=self.armed;self.armed=bool(msg.base_mode&128);self.hb=now
                    parked=not self.armed and msg.system_status==3
                    if not self.parked or not parked:self.parked_since=now
                    self.parked=parked
                    if self.armed:
                        self.flight=state.get("flight_session_id")
                    elif was is True:
                        self.want=True;self.next_run=now+12;self.failures=0;self.diagnostics={}
                    if self.armed or not parked:self.landed=False
            elif source==self.target and kind=="EXTENDED_SYS_STATE":
                self.landed=msg.landed_state==1;self.ground=now
                self.tries=0;self.next_ground_query=0.
            elif (source==self.target and kind=="FILE_TRANSFER_PROTOCOL" and self.current
                    and msg.target_system==CLIENT_SYS and msg.target_component==CLIENT_COMP and self.safe(now)):
                raw=bytes(msg.payload)
                if len(raw)>=12 and HEADER.unpack_from(raw)[0]==(self.current.seq+1)&65535:
                    try:self.rx.put_nowait((self.generation,raw))
                    except queue.Full:pass
        # The receive loop is the sole writer. The file worker never receives a serial descriptor.
        if not self.safe(now):
            if self.busy or self.current:
                self.generation+=1;self.current=None;self.busy=False
            if (self.enabled and self.parked and self.hb>0 and 0<=now-self.hb<2 and now>=self.blocked_to
                    and now-self.parked_since>=5 and (self.want or self.busy) and now>=self.next_run
                    and now>=self.next_ground_query and now-self.last_query>=3 and not self.stop.is_set()
                    and not self.held()):
                self.last_query=now
                self.writer.command_long_send(*self.target,512,0,245,0,0,0,0,0,0)
                self.last_tx=now;self.query_count+=1;self.tries+=1
                if self.tries>=3:
                    self.tries=0;self.next_ground_query=now+120;self.last_state="ground_confirmation_unavailable"
            return
        if (self.busy or (self.want and now>=self.next_run)) and now-self.ground>=2 and now-self.last_query>=3:
            self.writer.command_long_send(*self.target,512,0,245,0,0,0,0,0,0)
            self.last_query=now;self.last_tx=now;self.query_count+=1
        if self.want and not self.busy and now>=self.next_run:
            self.busy=True;self.generation+=1;self.wake.set()
        try:epoch,req=self.tx.get_nowait()
        except queue.Empty:return
        if self.busy and epoch==self.generation:
            self.current=req
            self.writer.file_transfer_protocol_send(0,*self.target,req.packet())
            self.last_tx=now;self.ftp_count+=1

    def report(self):
        return {"state":self.last_state,"active":self.busy,"ground_queries":self.query_count,
                "mavftp_reads_and_session_closes":self.ftp_count,
                "recent_tx":self.clock()-self.last_tx<2,
                "storage_probe":self.diagnostics,"retry_in_seconds":max(0,round(self.next_run-self.clock())),
                "capabilities":["request_message_245","list_log_directory","open_log_read_only",
                                "read_log_bytes","close_own_file_session","inspect_root_and_apm_first_page"]}

    def exchange(self,epoch,req):
        if epoch!=self.generation or not self.safe(self.clock()):raise Deferred("parked_guard_lost")
        while True:
            try:self.rx.get_nowait()
            except queue.Empty:break
        try:self.tx.put((epoch,req),timeout=.2)
        except queue.Full:raise Deferred("telemetry_link_busy")
        end=self.clock()+.9
        while self.clock()<end:
            if epoch!=self.generation or not self.safe(self.clock()):raise Deferred("parked_guard_lost")
            try:got,data=self.rx.get(timeout=.05)
            except queue.Empty:continue
            if got==epoch:return data
        return None

    def worker(self):
        while not self.stop.is_set():
            if not self.wake.wait(.2):continue
            self.wake.clear()
            if self.stop.is_set():break
            epoch=self.generation
            try:
                store=Intake(self.home)
                ftp=FTP(lambda req:self.exchange(epoch,req))
                marker_only=False
                try:
                    files=ftp.listing()
                except Deferred as original:
                    if not str(original).startswith("file_service_declined_list_"):raise
                    if not self.diagnostics:
                        self.diagnostics={"root_has_apm":ftp.directory_hint(b"/",b"APM"),
                                          "apm_has_logs":ftp.directory_hint(b"/APM",b"LOGS")}
                    try:
                        index=ftp.newest()
                        label=f"{index:08d}.BIN"
                        files={label:ftp.size(label)}
                        self.diagnostics={**self.diagnostics,"direct_marker":"available"}
                        marker_only=True
                    except Deferred as other:
                        self.diagnostics={**self.diagnostics,"direct_marker":str(other)}
                        raise original
                if files:
                    newest=ftp.newest()
                    current=[p for p in files if int(p.split(".")[0])==newest]
                    if len(current)!=1:raise Deferred("current_log_not_in_listing")
                    first=current[0]
                    for name in [first,*sorted((n for n in files if n!=first),reverse=True)]:
                        if not files[name]:continue
                        origin="native-selected-controller"
                        def validate():
                            return (self.safe(self.clock()) and epoch==self.generation and
                                    (ftp.size(name) if marker_only else ftp.listing().get(name))==files[name]
                                    and ftp.newest()==newest)
                        report=store.copy(origin,name,files[name],ftp.stream(name,files[name]),validate,
                                          name!=first,self.flight if name==first else None)
                        if name==first and report["classification"]=="stable_snapshot":
                            publish_json(store.root/"latest-snapshot.json",report)
                            self.summarize(store,report,epoch)
                self.last_state="acquired" if files else "no_controller_log"
                if self.generation==epoch:self.want=False;self.failures=0
            except (Deferred,OSError,ValueError,KeyError) as exc:
                self.last_state=str(exc) if isinstance(exc,Deferred) else "local_storage_or_transport_unavailable"
                delay=(30,300,900,1800)[min(self.failures,3)]
                self.failures+=1
                self.next_run=self.clock()+delay
                self.want=True
            finally:
                if self.generation==epoch:self.busy=False;self.current=None

    def summarize(self,store,record,epoch):
        # Separate process keeps disk parsing and the installed model outside the UART loop.
        interpreter="/opt/orangepi-flight-log/venv/bin/python3"
        helper=str(Path(__file__).with_name("postflight_summary.py"))
        with subprocess.Popen([interpreter,"-B",helper,record["sha256"]],
                              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL) as process:
            try:
                while process.poll() is None:
                    if epoch!=self.generation or not self.safe(self.clock()):
                        raise Deferred("parked_guard_lost")
                    self.stop.wait(.1)
                if process.returncode:raise Deferred("snapshot_decode_deferred")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def close(self):
        self.stop.set();self.generation+=1;self.wake.set()
        if self.thread:self.thread.join(1)
