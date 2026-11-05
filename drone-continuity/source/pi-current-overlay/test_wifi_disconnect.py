import importlib.machinery,importlib.util,io,pathlib,socket,struct,tempfile,unittest
from unittest.mock import Mock,patch
loader=importlib.machinery.SourceFileLoader('wifi_disconnect_helper',str(pathlib.Path(__file__).with_name('orangepi-wifi-control')))
spec=importlib.util.spec_from_loader(loader.name,loader);helper=importlib.util.module_from_spec(spec);loader.exec_module(helper)
class DisconnectTests(unittest.TestCase):
 def exercise(self,error=None,uid=1000):
  conn=Mock();conn.getsockopt.return_value=struct.pack('3i',1,uid,1);conn.makefile.return_value=io.BytesIO(b'{"action":"status"}\n');conn.sendall.side_effect=error
  with tempfile.TemporaryDirectory() as folder,patch.object(helper,'RUNTIME',pathlib.Path(folder)),patch.object(helper.os,'dup',return_value=123),patch.object(helper.socket,'socket',return_value=conn),patch.object(helper,'dispatch',return_value={'ok':True}) as dispatch:
   try:helper.main()
   finally:conn.close.assert_called_once()
   if uid==1000:dispatch.assert_called_once_with({'action':'status'})
   else:dispatch.assert_not_called();self.assertIn(b'Only the companion account',conn.sendall.call_args[0][0])
 def test_reply(self):self.exercise()
 def test_closed_client(self):self.exercise(BrokenPipeError())
 def test_reset_client(self):self.exercise(ConnectionResetError())
 def test_timed_out_client(self):self.exercise(socket.timeout())
 def test_other_errors_remain_visible(self):
  with self.assertRaises(OSError):self.exercise(OSError('unexpected'))
 def test_wrong_uid_cannot_dispatch(self):self.exercise(uid=1001)
if __name__=='__main__':unittest.main()
