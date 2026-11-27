"""Prepare the separately reviewed read-only acquisition hook for the installed monitor baseline."""
import hashlib
from pathlib import Path

BASE="5d2b17b71e38521afc6940c27ec458093fd905863569344c7ee50b77a42ac464"


def patched(raw):
    if hashlib.sha256(raw).hexdigest()!=BASE:raise ValueError("Unexpected installed monitor version.")
    source=raw.decode()
    def replace(old,new):
        nonlocal source
        if source.count(old)!=1:raise ValueError("Unexpected monitor source.")
        source=source.replace(old,new)
    replace('    last_heartbeat = time.monotonic()\n    last_write = 0.0',
        '''    last_heartbeat = time.monotonic()
    last_write = 0.0
    collector = None
    if device == "/dev/h743" and Path(device).resolve() == Path("/dev/ttyS0"):
        import sys
        helpers = "/usr/local/lib/orangepi-postflight-intake"
        sys.path.insert(0,helpers)
        try:
            from onboard_postflight import Collection, CLIENT_SYS, CLIENT_COMP
            class NonblockingWriter:
                def write(self,frame):
                    if link.port.write(frame)!=len(frame):
                        raise OSError("Postflight query frame did not fit")
            stream = mavutil.mavlink.MAVLink(NonblockingWriter(), srcSystem=CLIENT_SYS, srcComponent=CLIENT_COMP)
            link.port.write_timeout = 0
            collector = Collection(Path.home(),expected_source,stream)
        except (ImportError, OSError, ValueError, AttributeError):
            state["postflight_reader"] = {"state":"reader_unavailable","active":False}
        finally:
            sys.path.remove(helpers)
    state["telemetry_provenance"] = "waiting_for_matching_controller"
    accepted_since_write = False''')
    replace('            message = link.recv_match(blocking=True, timeout=0.5)',
            '''            timeout = .025 if collector and collector.busy else .5
            if accepted_since_write:
                timeout = min(timeout,max(.001,.10 - (time.monotonic()-last_write)))
            message = link.recv_match(blocking=True, timeout=timeout)''')
    replace('            if message is not None and message.get_type() != "BAD_DATA":\n                accepted = update_message(state, message)',
        '''            if message is not None and message.get_type() != "BAD_DATA":
                accepted = update_message(state, message)
                accepted_since_write |= accepted
                if accepted:state["telemetry_provenance"] = "observed_from_matching_controller"''')
    replace('            if now - last_write >= 0.25:\n                atomic_json(state)\n                last_write = now',
        '''            if collector:
                try:
                    collector.observe(message if message is not None and message.get_type()!="BAD_DATA" else None,state)
                    info = collector.report()
                    state["postflight_reader"] = info
                    state["authority"] = ("read_only_postflight_file_queries" if info["recent_tx"] or info["active"]
                                          else "read_only_no_mavlink_transmit")
                except (OSError, ValueError, RuntimeError):
                    collector.close();collector=None
                    state["postflight_reader"] = {"state":"reader_io_error","active":False}
                    # Preserve fail-closed authority until a new verified native connection.
                    state["authority"] = "read_only_postflight_file_queries"
            if now - last_write >= (.10 if accepted_since_write else .5):
                atomic_json(state)
                last_write = now
                accepted_since_write = False''')
    replace('    finally:\n        link.close()\n','    finally:\n        if collector:collector.close()\n        link.close()\n')
    compile(source,"orangepi-mavlink-monitor","exec")
    return source.encode()
