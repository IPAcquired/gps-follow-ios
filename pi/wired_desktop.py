"""Serve the existing owner desktop to the verified wired display for one session."""
import argparse
import collections
import contextlib
import queue
import secrets
import sys
import time
from pathlib import Path

from PIL import Image
from desktop_source import OwnerDesktop, Pattern, FrameWorker, FocusRequest
from display_model import CLEAR, HEARTBEAT, Gesture, HEIGHT, WIDTH, Zoom, initial_background, desktop_updates, pattern_patches, with_pointer
from scene_codec import ObjectUpdate, select_plan, zlib_updates, interactive_plan


def checked_port(path, topology):
    node = Path(path).resolve(strict=True)
    if not node.name.startswith("ttyACM"):
        raise ValueError("Select the verified XIAO USB CDC port.")
    interface = (Path("/sys/class/tty") / node.name / "device").resolve(strict=True)
    for parent in (interface, *interface.parents):
        if (parent / "idVendor").exists():
            vid = (parent / "idVendor").read_text().strip().lower()
            pid = (parent / "idProduct").read_text().strip().lower()
            if parent.name == topology and (vid, pid) == ("2886", "0058"):
                return str(node)
            break
    raise ValueError("Selected USB location or XIAO vendor/product differs from the approved device.")


class Link:
    def __init__(self, serial, touch, health):
        self.serial, self.touch, self.health = serial, touch, health
        self.buffer = bytearray()
        self.lines = collections.deque()
        self.seq = secrets.randbelow(65535) + 1
        self.last_ping = 0
        self.last_event = None
        self.active = False

    def write(self, command):
        wire = (command + "\n").encode("ascii")
        if self.serial.write(wire) != len(wire):
            raise OSError("Incomplete USB write.")

    def next_line(self, deadline):
        while time.monotonic() < deadline:
            self.health()
            if self.active and time.monotonic() - self.last_ping >= 0.55:
                self.write("PING")
                self.last_ping = time.monotonic()
            if not self.lines:
                self.buffer.extend(self.serial.read(min(2048, self.serial.in_waiting or 1)))
                if len(self.buffer) > 4096:
                    raise ValueError("Malformed desktop USB response.")
                chunks = self.buffer.split(b"\n")
                self.buffer = bytearray(chunks.pop())
                self.lines.extend(chunk.strip().decode("ascii") for chunk in chunks if chunk.strip())
                continue
            line = self.lines.popleft()
            if line.startswith("TOUCH "):
                words = line.split()
                if len(words) != 5:
                    raise ValueError("Unexpected touch record.")
                seq, state, x, y = map(int, words[1:])
                if not (0 <= seq <= 65535 and state in (1, 2) and 0 <= x < WIDTH and 0 <= y < HEIGHT):
                    raise ValueError("Touch record outside viewport.")
                if seq != self.last_event:
                    self.last_event = seq
                    self.touch(state, x, y)
                continue
            if line == "LOST":
                raise RuntimeError("The wired screen session ended.")
            if line == "PONG":
                continue
            return line
        return None

    def expect(self, response, seconds=2):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            line = self.next_line(deadline)
            if line == response:
                return
            if line and line.startswith("ERROR"):
                raise RuntimeError("The XIAO declined the USB command.")
        raise RuntimeError("The expected XIAO firmware did not reply.")

    def begin(self):
        self.write("HELLO")
        self.expect("DESKTOP XIAO 1")
        self.write("BEGIN")
        self.expect("READY")
        self.active = True
        self.last_ping = time.monotonic()

    def send(self, payload, seconds=3):
        if not 1 <= len(payload) <= 62:
            raise ValueError("Invalid desktop packet length.")
        deadline = time.monotonic() + seconds
        retry_at = 0
        while time.monotonic() < deadline:
            if time.monotonic() >= retry_at:
                self.write(f"PUT {self.seq} {payload.hex()}")
                retry_at = time.monotonic() + 0.5
            line = self.next_line(min(retry_at, deadline))
            if line == f"ACK {self.seq}":
                self.seq = self.seq % 65535 + 1
                return
            if line in (None, "BUSY", f"QUEUED {self.seq}"):
                continue
            if line == "ERROR SEQUENCE":
                self.seq = self.seq % 65535 + 1
                retry_at = 0
                continue
            if line.startswith("ERROR"):
                raise RuntimeError("The XIAO rejected a desktop packet.")
        raise RuntimeError("The screen did not acknowledge drawing the packet.")

    def end(self):
        if self.active:
            self.active = False
            self.write("END")


def same_neighborhood(frame, present, x, y):
    box = (max(0, x-4), max(0, y-4), min(WIDTH, x+5), min(HEIGHT, y+5))
    return frame.crop(box).tobytes() == present.crop(box).tobytes()


def pointer_updates(present, target, old, new):
    boxes = [box for box in (old, new) if box is not None]
    if old and new and old[0] <= new[2] and new[0] <= old[2] and old[1] <= new[3] and new[1] <= old[3]:
        boxes = [(min(old[0], new[0]), min(old[1], new[1]),
                  max(old[2], new[2]), max(old[3], new[3]))]
    return [item for box in boxes for item in zlib_updates(present, target, box)]


def serve(serial, worker, duration=None, *, link_factory=Link, notice=lambda name, value: False,
          direct_usb=False):
    present = Image.new("LA", (WIDTH, HEIGHT))
    gesture = Gesture()
    touch_ready = False
    present_view=None
    staged_target=None
    testing = isinstance(worker.source, Pattern)
    timed_tap = None
    last_tap = None
    invalidate=False
    lower_blocked=False
    zoom=Zoom()
    zoom_wait=zoom_painted=None
    focus_revision=work_item=None
    cached_key=cached=cached_clean=cached_background=None
    present_clean=None
    def projected():
        nonlocal cached_key,cached,cached_clean,cached_background
        ident,frame,view=worker.snapshot()
        key=ident,zoom.revision
        if key!=cached_key:
            if frame is None:
                cached = (None, view)
            else:
                if cached_clean is not frame or cached_key is None or cached_key[1] != zoom.revision:
                    cached_background = zoom.background(frame, view)
                cached = with_pointer(*cached_background, view.pointer)
            cached_key=key
            cached_clean=frame
        return key,*cached
    def touch(state, x, y):
        nonlocal timed_tap,focus_revision,last_tap
        _, latest, view = projected()
        current_place=(touch_ready and zoom_wait is None and latest is not None and view==present_view and not (lower_blocked and y>=152)
                       and same_neighborhood(latest,present,x,y))
        if not current_place or (staged_target is not None and not same_neighborhood(staged_target,present,x,y)):
            gesture.invalid = True
        command = gesture.feed(state, x, y, view)
        if command:
            try:
                focus_revision=None
                worker.commands.put_nowait(command)
                if command["type"] == "tap":
                    last_tap = (time.monotonic(), (x,y))
                if testing and command["type"] == "tap" and 80 <= x <= 175 and 64 <= y <= 139:
                    timed_tap = (time.monotonic(), present.getpixel((120,90)))
            except queue.Full as exc:
                raise RuntimeError("Touch events arrived faster than the desktop accepted them.") from exc

    link = link_factory(serial, touch, worker.snapshot)
    def accept_control(kind,seq,instruction):
        nonlocal invalidate,lower_blocked,zoom_wait,zoom_painted,focus_revision,work_item,touch_ready
        worker.snapshot()
        if kind==0x26:
            invalidate=lower_blocked=True
            focus_revision=None
            return True
        if kind==0x27:
            if zoom_painted==seq:
                zoom_wait=zoom_painted=None
                return True
            if zoom_wait is None:
                zoom.command(instruction);zoom_wait=seq
                touch_ready=False;focus_revision=None
                if gesture.start is not None:gesture.invalid=True
            return False
        if testing or first_paint or zoom_wait is not None:return "reject"
        if kind not in (0x24,0x28):return False
        if work_item is None:
            if kind==0x24 and focus_revision is None:
                if getattr(link,"capabilities",0)&16:return "reject"
                focus_revision=worker.source.focus()
                if focus_revision is None:return "reject"
            request=FocusRequest(instruction,focus_revision)
            try:worker.commands.put_nowait(request)
            except queue.Full:return False
            work_item=seq,request
        queued,request=work_item
        if queued!=seq:raise RuntimeError("Paired input order changed.")
        if not request.done.is_set():return False
        work_item=None
        if kind==0x28:focus_revision=request.result
        if not request.result:
            focus_revision=None;return "reject"
        return True
    link.control=accept_control
    deadline = time.monotonic() + duration if duration is not None else None
    first_paint = True
    try:
        link.begin()
        link.send(HEARTBEAT)
        notice("peer-capabilities",getattr(link,"capabilities",0))
        if testing or not getattr(link,"capabilities",0)&4:
            link.send(CLEAR);link.send(HEARTBEAT)
        last_beat = time.monotonic()
        paint_started = last_beat
        last_id, start, plan = None, 0, None
        hold_plan=False
        shown_cursor = under_cursor = None
        pointer_remaining = minimum_tasks = 0
        committed=0
        last_progress=paint_started
        while deadline is None or time.monotonic() < deadline:
            key, target, view = projected()
            # A heartbeat ACK can dispatch a touch and take a newer snapshot.
            # Keep the background paired with the target selected for this iteration.
            target_clean, target_background = cached_clean, cached_background
            if last_tap and time.monotonic()-last_tap[0] >= 1.2:
                last_tap = None
            if invalidate:
                invalidate=False;lower_blocked=True
                link.send(bytes.fromhex("010000009801e000900000"))
                present.paste((0,0),(0,152,WIDTH,HEIGHT))
                last_id=-1;plan=None;present_clean=None
                pointer_remaining=minimum_tasks=0
            if time.monotonic() - last_beat >= 0.5:
                link.send(HEARTBEAT)
                last_beat = time.monotonic()
            # Paint one internally consistent initial capture even when the Linux cursor
            # or clock is moving. Freshness and stale-tap checks keep using the live worker.
            if key != last_id and not ((first_paint or hold_plan or minimum_tasks) and plan is not None):
                if target is None:
                    raise RuntimeError("The desktop has no authenticated frame.")
                capabilities=getattr(link,"capabilities",0)
                if last_id is None and (testing or not capabilities&4):
                    background = initial_background(target)
                    if background:
                        link.send(background.packet)
                        background.apply(present)
                encode_started=time.monotonic()
                cursor_only = (direct_usb and capabilities&1 and target_clean is present_clean
                               and present_view is not None and view == present_view and zoom_wait is None)
                working = present
                pointer_prefix = []
                scroll_change = zoom_wait is not None or (present_view is not None and view != present_view)
                prefix_box = view.pointer_box
                prefix_background = target_background[0]
                if direct_usb and capabilities&1 and not first_paint:
                    if scroll_change and shown_cursor and under_cursor is not None:
                        restore = present.copy()
                        restore.paste(under_cursor,shown_cursor[:2])
                        pointer_prefix = pointer_updates(present,restore,shown_cursor,None)
                        prefix_box = None
                    elif not scroll_change and (cursor_only or shown_cursor != view.pointer_box):
                        pointer_prefix = pointer_updates(present,target,shown_cursor,view.pointer_box)
                    if pointer_prefix:
                        working=present.copy()
                        for _,item in pointer_prefix:item.apply(working)
                planned = []
                if not cursor_only:
                    planned=(list(pattern_patches(present,target,start)) if testing
                             else select_plan(working,target,start,first_paint or zoom_wait is not None,
                                              capabilities,direct_usb=direct_usb,jpeg_background=target_background[0]))
                pointer_started = (encode_started if cursor_only and pointer_prefix and shown_cursor
                                   and view.pointer_box and shown_cursor != view.pointer_box else None)
                planned_clean=target_clean
                planned_background=target_background
                present_clean=None
                planned_view=view
                planned_target=target
                full_scene=any(isinstance(item,ObjectUpdate) and item.kind=="jpeg" for _,item in planned)
                feedback_started = None
                if (direct_usb and capabilities&1 and not cursor_only and not testing and not first_paint
                        and zoom_wait is None and planned):
                    anchor = None
                    if last_tap:
                        anchor = last_tap[1]
                    elif view.pointer_box:
                        x,y,right,bottom = view.pointer_box
                        anchor = ((x+right)//2, (y+bottom)//2)
                    planned = interactive_plan(working,target,planned,anchor,getattr(link,"graphics_burst",1))
                    feedback_started = encode_started
                pointer_remaining=len(pointer_prefix)
                # Finish erasing/drawing this cursor and at least one real content update
                # before replacing a partially painted desktop with a newer hover frame.
                minimum_tasks=pointer_remaining+(1 if pointer_remaining and planned else 0)
                planned=pointer_prefix+planned
                hold_plan=full_scene or zoom_wait is not None or cursor_only
                if full_scene:notice("scene-encode",round((time.monotonic()-encode_started)*1000,2))
                plan=iter(planned)
                if first_paint:
                    notice("initial-plan",sum(len(p.packets) if isinstance(p,ObjectUpdate) else 1 for _,p in planned))
                last_id = key
            if plan is not None:
                task = next(plan, None)
                if task:
                    start, patch = task
                    scene=isinstance(patch,ObjectUpdate) and patch.kind=="jpeg"
                    wires=patch.packets if isinstance(patch,ObjectUpdate) else (patch.packet,)
                    sent_at=time.monotonic()
                    if scene:
                        staged_target=planned_target
                        notice("scene-start",patch.encoded_size)
                    index=0
                    while index<len(wires):
                        if time.monotonic()-last_beat>=.5:
                            link.send(HEARTBEAT);last_beat=time.monotonic()
                        wire=wires[index]
                        if scene and wire==b"\x0b":
                            touch_ready=False
                            if gesture.start is not None:gesture.invalid=True
                        # Keep all commits, controls and heartbeat barriers on the single-record path.
                        end=index+1
                        if wire[0] in (7,10):
                            limit=min(len(wires),index+getattr(link,"graphics_burst",1))
                            while end<limit and wires[end][0]==wire[0]:
                                end+=1
                        if end-index>1:
                            link.send_graphics(wires[index:end])
                        else:
                            link.send(wire)
                        committed+=end-index
                        index=end
                        if first_paint and time.monotonic()-last_progress>=2:
                            notice("first-progress",committed);last_progress=time.monotonic()
                    patch.apply(present)
                    if minimum_tasks:minimum_tasks-=1
                    was_pointer=bool(pointer_remaining)
                    if pointer_remaining:
                        pointer_remaining-=1
                        if not pointer_remaining:
                            shown_cursor=prefix_box
                            under_cursor=prefix_background.crop(shown_cursor) if shown_cursor else None
                    if feedback_started is not None and not was_pointer:
                        notice("first-feedback-ack",round((time.monotonic()-feedback_started)*1000,2))
                        feedback_started = None
                    if scene:
                        staged_target=None
                        notice("scene-commit",round(time.monotonic()-sent_at,3))
                        # JPEG carried only the desktop. A cursor can move while the
                        # receiver is staging it. Paint the current hotspot, never a
                        # glyph left over from the beginning of a seconds-long upload.
                        _,_,latest_view=worker.snapshot()
                        hotspot=latest_view.pointer if latest_view is not None and zoom.revision==last_id[1] else None
                        planned_target,planned_view=with_pointer(*planned_background,hotspot)
                        shown_cursor=under_cursor=None
                        restore=pointer_updates(present,planned_target,None,planned_view.pointer_box)
                        prefix_box=planned_view.pointer_box
                        prefix_background=planned_background[0]
                        pointer_remaining=minimum_tasks=len(restore)
                        plan=iter(restore)
                    elif not first_paint:notice("dirty-commit",(len(wires),round((time.monotonic()-sent_at)*1000)))
                    if timed_tap and present.getpixel((120,90)) != timed_tap[1]:
                        elapsed = round(1000 * (time.monotonic() - timed_tap[0]))
                        print(f"USB release receipt to LCD color-change acknowledgement: {elapsed} ms.", flush=True)
                        if notice("verified-pattern", elapsed):
                            return
                        timed_tap = None
                    continue
                plan = None
                hold_plan=False
                present_view=planned_view
                present_clean=planned_clean
                if shown_cursor and shown_cursor==planned_view.pointer_box:
                    under_cursor=planned_background[0].crop(shown_cursor)
                if pointer_started is not None:
                    notice("pointer-commit",round((time.monotonic()-pointer_started)*1000,2))
                touch_ready = last_id[1]==zoom.revision
                if touch_ready and zoom_wait is not None:
                    zoom_painted=zoom_wait
                    notice("zoom-committed",zoom.level)
                lower_blocked=False
                notice("paint", last_id[0])
                if first_paint:
                    notice("first-seconds",round(time.monotonic()-paint_started,2))
                    print("First complete viewport acknowledged.", flush=True)
                    if testing:
                        print(f"Pattern first-paint acknowledgement: {time.monotonic()-paint_started:.2f} s.",flush=True)
                    first_paint = False
            link.next_line(time.monotonic() + 0.015)
    finally:
        worker.stop.set()
        with contextlib.suppress(Exception):
            link.health = lambda: None
            link.touch = lambda *args: None
            if link.active and not getattr(link,"owns_final_clear",False):
                link.send(CLEAR, seconds=0.35)
        with contextlib.suppress(Exception):
            link.end()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("pattern", "owner"))
    parser.add_argument("--port", required=True)
    parser.add_argument("--usb-path", required=True, help="Verified physical topology for the XIAO.")
    parser.add_argument("--seconds", type=float, default=None, help="Optional shorter test duration.")
    args = parser.parse_args()
    if args.seconds is not None and not 0.1 <= args.seconds <= 300:
        parser.error("--seconds must be between 0.1 and 300")
    import serial
    node = checked_port(args.port, args.usb_path)
    source = Pattern() if args.mode == "pattern" else OwnerDesktop()
    source.authorize()
    with serial.Serial(node, 115200, timeout=.005, write_timeout=.35, exclusive=True) as transport:
        transport.reset_input_buffer()
        # A different USB application must never trigger an owner-desktop capture.
        probe = Link(transport, lambda *args: None, lambda: None)
        probe.write("HELLO")
        probe.expect("DESKTOP XIAO 1")
        worker = FrameWorker(source)
        worker.thread.start()
        try:
            if not worker.ready.wait(5) or worker.snapshot()[1] is None:
                raise RuntimeError("The protected desktop source is unavailable.")
            serve(transport, worker, args.seconds)
        finally:
            worker.stop.set()
            worker.thread.join(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError) as exc:
        sys.exit(str(exc))
