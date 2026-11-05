import ast,io,pathlib,secrets,ssl,time,types,unittest
from http import HTTPStatus
from unittest.mock import patch
import desktop_capture
source=ast.parse(pathlib.Path(__file__).with_name('orangepi-companion').read_text(encoding='utf-8'))
handler=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
ns=dict(HTTPStatus=HTTPStatus,secrets=secrets,time=time,ssl=ssl,desktop_capture=desktop_capture)
for name in ('do_GET','remote_input'):
 fn=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name==name)
 exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual_handler','exec'),ns)
class Request:
 path='/api/desktop/frame';client_address=('192.168.1.10',1);connection=None;authorized=True
 def require_auth(self):
  if not self.authorized:self.send_json(401,{})
  return self.authorized
 def send_json(self,code,body):self.code=code
 do_GET=ns['do_GET'];remote_input=ns['remote_input']
class DesktopTests(unittest.TestCase):
 def test_private_source_required(self):
  r=Request();r.do_GET();self.assertEqual(r.code,403)
  r.remote_input();self.assertEqual(r.code,403)
 def test_plaintext_rejected_even_for_display_address(self):
  r=Request();r.client_address=('10.42.0.2',1);r.do_GET();self.assertEqual(r.code,403)
  r.remote_input();self.assertEqual(r.code,403)
 def test_auth_required_for_images(self):
  r=Request();r.authorized=False;r.do_GET();self.assertEqual(r.code,401)
 def test_pointer_bounds_reject_without_execution(self):
  with patch.object(desktop_capture.subprocess,'run',side_effect=AssertionError('must not run')):
   for x,y in ((-1,0),(10001,0),(0,10001),(True,0),(1.2,0),(0,'1')):
    with self.assertRaises(ValueError):desktop_capture.point(x,y)
 def test_capture_requires_complete_frame(self):
  desktop_capture._last=0
  with patch.object(desktop_capture.subprocess,'run',side_effect=[types.SimpleNamespace(stdout='1024 768'),types.SimpleNamespace(stdout=b'broken')]):
   with self.assertRaises(RuntimeError):desktop_capture.capture()
 def test_pointer_mapping(self):
  with patch.object(desktop_capture.subprocess,'run',return_value=types.SimpleNamespace(stdout='1024 768')) as run:
   desktop_capture.point(10000,10000)
   self.assertEqual(run.call_args.args[0][-2:],['1023','767'])
