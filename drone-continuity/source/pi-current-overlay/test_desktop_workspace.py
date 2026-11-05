import ast,pathlib,types,unittest
from unittest.mock import patch
import desktop_workspace as d

class WorkspaceTests(unittest.TestCase):
 def setUp(self):d._size=None;d._checked=0;d._active=False;d._opened=False
 def test_only_native_canvas_dimensions(self):
  with patch.object(d,'command') as run:
   for size in [(0,0),(320,480),(8192,8192),(500,300)]:
    with self.assertRaises(ValueError):d.ensure_size(*size)
   run.assert_not_called()
 def test_attached_monitor_not_reconfigured(self):
  with patch.object(d,'command',return_value=types.SimpleNamespace(stdout='HDMI-1 connected primary 1920x1080+0+0')) as run:
   self.assertFalse(d.ensure_size(320,436));self.assertFalse(d._active);self.assertEqual(run.call_count,1)
 def test_unchanged_monitor_not_recreated(self):
  answers=[types.SimpleNamespace(stdout='current 320 x 436,'),types.SimpleNamespace(stdout='0: AXL-ESP32 320/85x436/115+0+0')]
  with patch.object(d,'command',side_effect=answers) as run,patch.object(d,'launch') as launch:
   self.assertTrue(d.ensure_size(320,436));self.assertTrue(d.ensure_size(320,436));self.assertEqual(run.call_count,2)
   launch.assert_called_once_with('apps')
 def test_launch_allowlist(self):
  with patch.object(d.subprocess,'Popen') as p:
   for value in ['terminal; rm','https://evil.invalid','../other','']:
    with self.assertRaises(ValueError):d.launch(value)
   p.assert_not_called();d.launch('files');self.assertEqual(p.call_args.args[0],['thunar','/home/drone'])
 def test_launcher_does_not_override_application_run(self):
  tree=ast.parse(pathlib.Path(__file__).with_name('orangepi-touch-desktop').read_text())
  cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
  self.assertNotIn('run',[n.name for n in cls.body if isinstance(n,ast.FunctionDef)])

if __name__=='__main__':unittest.main()
