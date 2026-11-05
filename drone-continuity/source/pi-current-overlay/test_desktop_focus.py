import unittest,time
from unittest.mock import patch
import desktop_focus as f
import desktop_capture as c

class FocusTests(unittest.TestCase):
 def test_unknown_never_opens_keyboard(self):
  with patch.multiple(f,_checked=0,_editable=True,_revision=12):
   self.assertEqual(f.snapshot(),{'known':False,'editable':False,'revision':12})
 def test_stale_focus_never_opens_keyboard(self):
  with patch.multiple(f,_checked=time.monotonic()-3,_editable=True):self.assertFalse(f.snapshot()['editable'])
 def test_fresh_editable_has_no_field_content(self):
  with patch.multiple(f,_checked=time.monotonic(),_editable=True,_revision=13):
   self.assertEqual(f.snapshot(),{'known':True,'editable':True,'revision':13})
 def test_noneditable(self):
  with patch.multiple(f,_checked=time.monotonic(),_editable=False):self.assertFalse(f.snapshot()['editable'])
 def test_tap_uses_single_pointer_and_click_process(self):
  with patch.object(c,'geometry',return_value=(1024,768,{})),patch.object(c.subprocess,'run') as run:
   c.point(10000,10000,click=True)
   run.assert_called_once()
   self.assertEqual(run.call_args.args[0],['/usr/bin/xdotool','mousemove','1023','767','click','1'])
 def test_bad_tap_cannot_click(self):
  with patch.object(c.subprocess,'run') as run:
   with self.assertRaises(ValueError):c.point(True,100,click=True)
   run.assert_not_called()

if __name__=='__main__':unittest.main()
