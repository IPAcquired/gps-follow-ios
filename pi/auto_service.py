"""The sole USB owner for on-demand and automatically paired touchscreen sessions."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import time
import serial

from desktop_source import DesktopUnavailable, FrameWorker
from bridge_usb import confirm_bridge, selection
from paired_system import (Status, GuardedDesktop, GuardedPattern, attach_generation, atomic_json,
                           enrollment, find_helper, private_dir, private_file, runtime)
from paired_wire import LinkEnded, LocalBack, PairWire, authenticate, wait_for_screen
from wired_desktop import serve
from direct_usb import DirectAttachment, find_direct


class ModeChanged(RuntimeError):
    pass

REASONS={1:"unlock the local graphical session",2:"wait for fresh, safe controller status",
         3:"check the local desktop broker",4:"resume desktop sharing on the Pi"}

class Service:
    def __init__(self):
        self.dir=runtime()
        self.status=Status(self.dir)
        self.topology=json.loads((Path(__file__).resolve().parent/"approved-usb.json").read_text())["topology"]
        self.direct_attachment=DirectAttachment()
        self.mode="auto"
        self.last_command=""
        # A diagnostic is one-shot. Explicit owner pause survives a service restart.
        try:
            last=json.loads(private_file(self.dir/"command.json",512))
            self.last_command=last.get("request","")
            self.mode="pause" if last.get("mode")=="pause" else "auto"
        except (FileNotFoundError,ValueError):pass
        self.next_command=0
        self.stop=False
        self.had_peer=False
        self.bad_xiao=None;self.bad_count=0;self.direct_cookie=None
        self.route=None;self.in_use=None;self.last_scan=0

    def controls(self):
        if self.stop: raise KeyboardInterrupt()
        if self.route=="direct USB" and time.monotonic()-self.last_scan>.8:
            self.last_scan=time.monotonic()
            _,candidate=find_helper(self.topology)
            if candidate and candidate!=self.bad_xiao and candidate!=self.in_use:
                raise ModeChanged  # A newly attached preferred bridge gets one bounded trial.
        if time.monotonic()<self.next_command: return
        self.next_command=time.monotonic()+.12
        try: request=json.loads(private_file(self.dir/"command.json",512))
        except FileNotFoundError: return
        mode=request.get("mode")
        token=request.get("request")
        if mode not in ("pattern","owner","pause") or token==self.last_command: return
        self.last_command=token;self.mode=mode
        raise ModeChanged

    def display(self,session,key):
        state_dir=private_dir(Path.home()/".local/state/orange-pi-wired-desktop")
        tag=hashlib.sha256(b"private-pattern-result"+key).hexdigest()[:32]
        receipt=state_dir/("verified-"+tag+".json")
        try: verified=json.loads(private_file(receipt,512)).get("physical_tap_verified") is True
        except (FileNotFoundError,ValueError): verified=False
        self.status.set(authenticated=True,pattern_verified=verified,os_inputs=0,updated_frame_after_input=0,
                        updated_lcd_after_input=0,desktop_full_paints=0,first_frame_acks=0,
                        first_frame_plan=0,first_frame_seconds=None,staged_jpeg_bytes=0,
                        last_source_capture_monotonic=None,last_lcd_ack_monotonic=None,
                        capture_to_lcd_seconds=None,staged_picture_commit_seconds=None,
                        dirty_update_records=0,dirty_update_ms=None,
                        pointer_updates=0,last_pointer_update_ms=None)
        if self.mode=="pattern":
            self.status.set(state="starting authenticated test pattern")
            pattern=GuardedPattern(session.channel,self.status)
            def event(kind,value):
                if kind=="paint":
                    self.status.set(state="tap the red rectangle")
                if kind=="verified-pattern":
                    atomic_json(receipt,{"physical_tap_verified":True})
                    self.status.set(state="verified touch and LCD update",pattern_verified=True,pattern_ms=value)
                    until=time.monotonic()+.7
                    while time.monotonic()<until: session.wire.next_line(min(until,time.monotonic()+.06))
                    return True
                return False
            self.run_view(session,pattern,event)
            self.mode="auto"
        desktop=GuardedDesktop(session.channel,self.status)
        self.status.set(state="opening authenticated desktop")
        last_dirty_status=0
        pointer_updates=0
        def event(kind,value):
            nonlocal last_dirty_status,pointer_updates
            if kind=="peer-capabilities":
                self.status.set(screen_capabilities=value)
            elif kind=="initial-plan":
                self.status.set(state="painting actual Linux desktop",first_frame_plan=value)
            elif kind=="first-progress":
                self.status.set(first_frame_acks=value)
            elif kind=="first-seconds":
                self.status.set(first_frame_seconds=value,first_frame_acks=self.status.data["first_frame_plan"])
            elif kind=="scene-start":
                session.start_scene_timing()
                self.status.set(staged_jpeg_bytes=value,state="staging full desktop picture")
            elif kind=="scene-encode":
                self.status.set(scene_encoding_ms=value)
            elif kind=="zoom-committed":
                self.status.set(zoom_level=value)
            elif kind=="scene-commit":
                self.status.set(staged_picture_commit_seconds=value,**session.finish_scene_timing())
            elif kind=="dirty-commit" and time.monotonic()-last_dirty_status>.5:
                last_dirty_status=time.monotonic()
                self.status.set(dirty_update_records=value[0],dirty_update_ms=value[1])
            elif kind=="pointer-commit":
                pointer_updates+=1
                self.status.set(pointer_updates=pointer_updates,last_pointer_update_ms=value)
            elif kind=="paint":
                desktop.paint(value)
                self.status.set(state="authenticated desktop visible")
            return False
        self.run_view(session,desktop,event)

    def run_view(self,session,source,event):
        worker=FrameWorker(source,direct_display=self.route=="direct USB" and isinstance(source,GuardedDesktop))
        worker.thread.start()
        reason=0
        try:
            if not session.wait_for_source(worker.ready,3) or worker.snapshot()[1] is None:
                raise PermissionError("Desktop guard paused.")
            serve(session.wire.serial,worker,link_factory=session.adapter,notice=event,
                  direct_usb=self.route == "direct USB")
        except DesktopUnavailable as error:
            reason=error.reason
            raise
        except ModeChanged:
            if self.mode=="pause":reason=4
            raise
        finally:
            worker.stop.set()
            session.touch=lambda *_:None
            with contextlib.suppress(Exception,KeyboardInterrupt):
                session.blank(reason)
            worker.thread.join(3)

    @contextlib.contextmanager
    def open_xiao(self,node):
        with serial.Serial(node,115200,timeout=.005,write_timeout=.35,exclusive=True) as transport:
            transport.reset_input_buffer()
            yield PairWire(transport,self.controls,self.status.set)

    def once(self):
        self.controls()
        if self.mode=="pause":
            self.direct_attachment.close()
            self.status.set(state="paused by owner",action=REASONS[4],authenticated=False)
            return False
        key=enrollment()
        node,cookie=find_helper(self.topology)
        if cookie!=self.bad_xiao:
            self.bad_count=0;self.bad_xiao=cookie
        chosen= "XIAO" if node else None
        mac=private_file(Path.home()/".config/orange-pi-wired-desktop/screen.mac",6)
        if not node or self.bad_count>=2:
            alt,other_cookie=find_direct(mac)
            if alt: chosen,node,cookie="direct USB",alt,other_cookie
        if chosen!="direct USB":
            self.direct_attachment.close()
        if not chosen:
            self.status.set(state="waiting for USB",action=selection(self.topology)[1],route="none",authenticated=False)
            return False
        self.route=chosen;self.in_use=cookie
        generation=attach_generation(self.dir,chosen+":"+cookie)
        self.status.set(state="waiting for paired screen",action="open Wired Desktop or reconnect the screen cable",
                        route=chosen,authenticated=False)
        opened=(self.open_xiao(node) if chosen=="XIAO" else
                self.direct_attachment.open(node,cookie,mac,self.controls))
        try:
            with opened as wire:
                try:
                    wire.begin()
                    wait_for_screen(wire,generation)
                    self.status.set(state="authenticating screen",action="wait for the paired screen proof",authenticated=False)
                    session=authenticate(wire,key)
                    if chosen=="XIAO":
                        confirm_bridge(self.topology,node,cookie,session.channel)
                        self.bad_count=0
                    self.status.set(action="none")
                    self.display(session,key)
                finally:
                    with contextlib.suppress(Exception):wire.end()
        except (ValueError,RuntimeError,OSError) as exc:
            if chosen=="XIAO" and not isinstance(exc,(ModeChanged,PermissionError,LocalBack)):
                self.bad_count+=1
            raise
        finally:
            self.route=None;self.in_use=None
        return True

    def run(self):
        lock=(self.dir/"serial-owner.lock").open("a")
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        signal.signal(signal.SIGTERM,lambda *_:setattr(self,"stop",True))
        backoff=.25
        try:
            while not self.stop:
                try:
                    self.once()
                    delay=.7;backoff=.25
                except ModeChanged:
                    self.status.set(state="changing requested view",authenticated=False)
                    delay=.08;backoff=.25
                except LocalBack:
                    self.status.set(state="closed at touchscreen",action="open Wired Desktop to resume",authenticated=False)
                    delay=.35;backoff=.25
                except DesktopUnavailable as error:
                    self.status.set(state="waiting for desktop authorization or fresh guard",
                                    action=REASONS.get(error.reason,"check local authorization"),authenticated=False)
                    delay=.8
                except PermissionError:
                    self.status.set(state="waiting for desktop authorization or fresh guard",
                                    action="check local authorization and fresh safety status",authenticated=False)
                    delay=.8
                except FileNotFoundError:
                    self.status.set(state="waiting for enrollment or USB",action="check pairing and USB data cable",authenticated=False)
                    delay=.8
                except (ValueError,RuntimeError,OSError) as error:
                    safe_reasons={"The wired screen session ended.","The expected XIAO firmware did not reply.",
                                  "The screen did not acknowledge drawing the packet.","Peer confirmation timed out.",
                                  "Paired display lease ended.","Local Back.",
                                  "Owner desktop authorization or fresh frames are unavailable.",
                                  "Direct peer confirmation timed out.","Direct screen did not answer in time."}
                    self.status.set(state="reconnecting to paired display",authenticated=False,
                                    last_failure_stage=self.status.data["state"],
                                    last_failure=str(error) if str(error) in safe_reasons else type(error).__name__)
                    delay=backoff
                    backoff=min(backoff*1.4,3)
                end=time.monotonic()+delay
                while not self.stop and time.monotonic()<end:
                    try: self.controls()
                    except ModeChanged: break
                    time.sleep(.08)
        except KeyboardInterrupt:
            pass
        finally:
            self.direct_attachment.close()
            self.status.set(state="stopped",authenticated=False);lock.close()


def command(mode):
    directory=runtime()
    if mode=="status":
        try: info=json.loads(private_file(directory/"status.json",8192))
        except FileNotFoundError: print("The paired display service has not started.");return
        print(json.dumps(info,separators=(",",":")))
        return
    atomic_json(directory/"command.json",{"mode":mode,"request":secrets.token_hex(10)})
    print("Display request recorded.")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("run","status","owner","pattern","pause"),default="owner",nargs="?")
    args=parser.parse_args()
    if args.mode=="run":Service().run()
    else:command(args.mode)
