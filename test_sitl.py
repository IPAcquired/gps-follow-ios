"""Read-only MAVFTP and analysis against loopback-only ArduPilot SITL with a preloaded synthetic SD."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest import mock
import tempfile
import time
from pymavlink import mavutil
if Path("/runtime/onboard_postflight.py").exists():sys.path.insert(0,"/runtime")
from onboard_postflight import CLIENT_COMP,CLIENT_SYS,Collection,FTP
from postflight_store import Deferred
from test_intake import dataflash


def run(marker_only=False):
    if os.getuid()==0 or {name for _,name in socket.if_nameindex()}!={"lo"}:
        raise RuntimeError("Requires an unprivileged isolated loopback-only network namespace")
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        home=Path.home()
        logs=root/"APM/LOGS"
        logs.mkdir(parents=True)
        # The fixture prepares the simulated card before the simulator starts.
        files={"00000001.BIN":dataflash(9),"00000002.BIN":dataflash(),"LASTLOG.TXT":b"2D\r\n"}
        for name,data in files.items():(logs/name).write_bytes(data)
        simulator=subprocess.Popen(["/sim","--model","quad","--base-port","6040","--home","0,0,0,0"],
                                   cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        connection=reader=None
        try:
            start=time.monotonic()
            while time.monotonic()-start<20 and simulator.poll() is None:
                try:
                    connection=mavutil.mavlink_connection("tcp:127.0.0.1:6040",source_system=CLIENT_SYS,source_component=CLIENT_COMP,retries=0)
                    break
                except OSError:time.sleep(.1)
            if not connection:raise RuntimeError("SITL did not start")
            hb=connection.wait_heartbeat(timeout=12)
            if not hb or hb.base_mode&128:raise RuntimeError("No disarmed simulator heartbeat")
            reader=Collection(home,(hb.get_srcSystem(),hb.get_srcComponent()),connection.mav)
            reader.observe(hb,{})
            observations={}
            while time.monotonic()-start<80:
                msg=connection.recv_match(blocking=True,timeout=.025)
                if msg:
                    kind=msg.get_type()
                    if kind=="HEARTBEAT":observations["system_status"]=msg.system_status
                    if kind=="EXTENDED_SYS_STATE":observations["landed_state"]=msg.landed_state
                reader.observe(msg,{})
                if not reader.want and not reader.busy:break
            print("SITL",reader.report(),observations,flush=True)
            assert reader.last_state=="acquired",reader.report()
            base=home/"flight-data"
            digest=hashlib.sha256(files["00000002.BIN"]).hexdigest()
            result=json.loads((base/"acquisition/latest-analysis.json").read_bytes())
            assert result["sha256"]==digest and result["message_types"]["TEST"]==20
            if marker_only:
                assert reader.diagnostics["direct_marker"]=="available"
                assert reader.diagnostics["apm_has_logs"]=="present"
            else:
                closed=next((base/"inbox").glob("*.BIN"))
                assert closed.read_bytes()==files["00000001.BIN"]
                assert len(list((base/"inbox").glob("*.BIN")))==1
            assert sorted(p.name for p in logs.iterdir())==sorted(files)
            assert all((logs/k).read_bytes()==v for k,v in files.items())
            print("Verified closed log delivery, provisional newest snapshot analysis, unchanged simulated FC files.",flush=True)
        finally:
            if reader:reader.close()
            if connection:connection.close()
            simulator.terminate()
            try:simulator.wait(3)
            except subprocess.TimeoutExpired:simulator.kill();simulator.wait()


if __name__=="__main__":
    run()
    with mock.patch.object(FTP,"listing",side_effect=Deferred("file_service_declined_list_2_28")):
        run(marker_only=True)
