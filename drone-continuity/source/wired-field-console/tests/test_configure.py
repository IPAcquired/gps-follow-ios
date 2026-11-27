"""Commissioning tests with synthetic USB identities and a temporary local broker socket."""
import contextlib
import io
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import configure_pi as setup
import pi_pair_provision as registrar

class Commission(unittest.TestCase):
 def test_fresh_screen_different_physical_routes_with_no_backup(self):
  import serial
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/"broker.sock";saved={"paired":False,"local_setup":False}
   sock=socket.socket(socket.AF_UNIX);sock.bind(str(path));path.chmod(0o600)
   self.addCleanup(sock.close)
   mac=bytes([2,0,0,0,0,1]);inner=b"X"*32;calls=[];installed=[]
   def exchange(_,action,**fields):
    if action=="wired_status":return dict(saved,display="Hosyond-E32R35T",firmware=setup.VERSION,screen_mac=mac.hex())
    self.assertEqual(action,"wired_pair_enroll");self.assertEqual(fields["key_hex"],inner.hex());saved["paired"]=True
    return {"accepted":True}
   def run(args,**kw):
    self.assertEqual(kw["input"],mac+b"1-2");calls.append(args[-1]);return types.SimpleNamespace(stdout=inner if args[-1]=="prepare" else b"ACTIVE")
   fake_serial=contextlib.nullcontext(); fake_serial.dtr=True;fake_serial.rts=True
   bridge=types.SimpleNamespace(node="/dev/bridge",topology="1-3",digest="a"*64)
   profile=root/".config/orange-pi-wired-desktop";profile.mkdir(parents=True,mode=0o700)
   with patch.object(Path,"home",return_value=root),patch.object(setup,"owner_broker_path",return_value=path),patch.object(setup,"topology",return_value="1-2"),patch.object(setup,"chosen_bridge",return_value=bridge),patch.object(setup,"exchange",side_effect=exchange),patch.object(serial,"Serial",return_value=fake_serial),patch.object(setup.subprocess,"run",side_effect=run),patch.object(setup,"stage_and_install",side_effect=installed.append),patch.object(sys,"argv",["configure_pi.py","--screen-port","/dev/screen","--bridge-port","/dev/bridge"]),contextlib.redirect_stdout(io.StringIO()) as output:
    setup.main()
   self.assertEqual(calls,["prepare","activate"]);self.assertEqual(installed,["1-3"])
   self.assertEqual(setup.read_pin(profile/"xiao-serial.sha256"),bridge.digest)
   self.assertFalse(fake_serial.dtr);self.assertFalse(fake_serial.rts);self.assertNotIn(inner.hex(),output.getvalue())
 def test_atomic_pair_without_prior_credentials(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/"private";pending=path/".pending-screen-pair";mac=bytes([2,0,0,0,0,55])
   def call(mode,identity=mac):
    stdout=types.SimpleNamespace(buffer=io.BytesIO(),write=lambda _:None,flush=lambda:None)
    with patch.object(sys,"stdin",types.SimpleNamespace(buffer=io.BytesIO(identity+b"2-1"))),patch.object(sys,"stdout",stdout):
     registrar.run(mode)
    return stdout.buffer.getvalue()
   with patch.object(registrar,"ROOT",path),patch.object(registrar,"PENDING",pending),patch.object(registrar,"inner",side_effect=lambda k:k):
    first=call("prepare");self.assertEqual(len(first),32);self.assertEqual(first,call("prepare"))
    call("activate");self.assertFalse(pending.exists());self.assertEqual(first,call("prepare"));call("activate")
    self.assertEqual(stat.S_IMODE((path/"pair.key").stat().st_mode),0o600)
    with self.assertRaises(ValueError):call("prepare",bytes([2,0,0,0,0,56]))
if __name__=="__main__":unittest.main()
