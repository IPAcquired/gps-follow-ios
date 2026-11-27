import unittest
from unittest.mock import patch
import wired_desktop as renderer
from display_model import Zoom
from test_interactive_paints import Receiver,Worker,white_box


class TestPointerFirst(unittest.TestCase):
    def test_mixed_prefix_starts_only_from_checked_frame_and_finishes_before_encoding(self):
        class Done(Exception):pass
        worker=Worker()
        events=[]
        peer=Receiver(self,worker,lambda *_:None)
        original=renderer.select_plan
        def plan(*args,**kwargs):
            if worker.ident==1:
                _,frame,view=worker.snapshot()
                self.assertEqual(white_box(peer.canvas),white_box(Zoom().project(frame,view)[0]))
                events.append("encode")
            return original(*args,**kwargs)
        def notice(kind,value):
            if kind=="paint" and value==0:worker.ident=1
            elif kind=="pointer-commit":events.append("pointer")
            elif kind=="paint" and value==1:raise Done
        with patch.object(renderer,"select_plan",plan),self.assertRaises(Done):
            renderer.serve(None,worker,4,link_factory=peer.start,notice=notice,direct_usb=True)
        self.assertEqual(events,["pointer","encode"])

    def test_loss_of_guard_between_erase_and_redraw_never_acknowledges_cursor(self):
        worker=Worker()
        allowed=[True]
        receipts=[]
        def policy(peer,event):
            if worker.ident and event=="drawn":
                allowed[0]=False
        peer=Receiver(self,worker,policy)
        send=peer.send
        def guarded_send(*args,**kwargs):
            if not allowed[0]:raise PermissionError("fixture guard revoked")
            return send(*args,**kwargs)
        peer.send=guarded_send
        def notice(kind,value):
            if kind=="paint" and value==0:worker.ident=1
            elif kind=="pointer-commit":receipts.append(value)
        with self.assertRaises(PermissionError):
            renderer.serve(None,worker,4,link_factory=peer.start,notice=notice,direct_usb=True)
        self.assertEqual(receipts,[])
        self.assertIsNone(white_box(peer.canvas))

    def test_zoom_requested_during_prefix_drops_old_geometry(self):
        class Checked(Exception):pass
        worker=Worker()
        peer=Receiver(self,worker,lambda *_:None)
        requested=[]
        original=renderer.select_plan
        def plan(current,target,*args,**kwargs):
            if requested:
                _,frame,view=worker.snapshot()
                zoom=Zoom();zoom.command(1)
                self.assertEqual(target.tobytes(),zoom.project(frame,view)[0].tobytes())
                raise Checked
            return original(current,target,*args,**kwargs)
        def notice(kind,value):
            if kind=="paint" and value==0:worker.ident=1
            if kind=="pointer-commit" and not requested:
                requested.append(True)
                self.assertFalse(peer.control(0x27,29,1))
        with patch.object(renderer,"select_plan",plan),self.assertRaises(Checked):
            renderer.serve(None,worker,4,link_factory=peer.start,notice=notice,direct_usb=True)
