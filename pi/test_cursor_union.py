import json
import random
import struct
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from display_model import LANDSCAPE, PORTRAIT, fit_frame, with_pointer
from scene_codec import ObjectUpdate, jpeg_scene, zlib_updates
from test_interactive_paints import Receiver
import wired_desktop as renderer


def frames(surface, old, new, background=None):
    clean, view = fit_frame(background or Image.new("RGB", surface, "#2c5471"), surface=surface)
    def mark(point):
        norm=tuple(round(n*65534/(axis-1)) for n,axis in zip(point,surface))
        image, v = with_pointer(clean, view, norm)
        return image,v.pointer_box
    present,a = mark(old)
    target,b = mark(new)
    return present,target,a,b


def serialized_cost(plan, burst, request_id, sequence):
    total = count = 0
    for _, update in plan:
        items = list(update.packets if isinstance(update,ObjectUpdate) else (update.packet,))
        while items:
            batch = [items.pop(0)]
            while len(batch)<burst and items and items[0][0]==batch[0][0] and items[0][0] in (7,10):
                batch.append(items.pop(0))
            authenticated=[bytes(len(item)+21) for item in batch]
            if len(batch)==1:
                cmd=dict(action="wired_usb_exchange",request_id=request_id,seq=sequence,down_hex=authenticated[0].hex())
            else:
                records=b"".join(bytes((len(v),))+v for v in authenticated)
                cmd=dict(action="wired_usb_burst1",request_id=request_id,first=sequence,records=records.hex())
            total+=len(json.dumps(cmd,separators=(",",":")).encode())+1
            count+=1
    return count,total


class CursorUnion(unittest.TestCase):
    def test_winner_is_pixel_identical_in_both_orientations_and_smaller_on_wire(self):
        for surface in (LANDSCAPE, PORTRAIT):
            p,t,a,b=frames(surface,(100,100),(118,102))
            known=Image.new("1",(surface[0],surface[1]-144),1)
            old=renderer.pointer_updates(p,t,a,b)
            new=renderer.pointer_updates(p,t,a,b,exact=known,burst=8)
            self.assertEqual((len(old),len(new)),(2,1))
            original=p.copy()
            original2=p.copy()
            for _,update in old:update.apply(original)
            for _,update in new:update.apply(original2)
            self.assertEqual(original.tobytes(),original2.tobytes())
            self.assertEqual(original2.tobytes(),t.tobytes())
            for plan in (old,new):
                for burst in (2,4,8):
                    for req,seq in ((1,1),(123456,12345),(4294967294,65535)):
                        self.assertEqual(renderer.cursor_wire_cost(plan,burst,len(str(req))+len(str(seq))),
                                         serialized_cost(plan,burst,req,seq))
            self.assertLess(serialized_cost(new,8,4294967294,65535),serialized_cost(old,8,1,1))
            self.assertLessEqual(serialized_cost(new,8,4294967294,65535)[1],serialized_cost(old,8,1,1)[1])

    def test_unknown_jpeg_gap_unmodelled_pixels_texture_and_local_controls_keep_old_packets(self):
        def packets(plan):
            return [v for _,u in plan for v in (u.packets if isinstance(u,ObjectUpdate) else (u.packet,))]
        surface=PORTRAIT
        noise=Image.frombytes("RGB",surface,random.Random(1).randbytes(surface[0]*surface[1]*3))
        for case in ("unknown","one_unknown","changed_gap","noise","near_bottom","too_far","no_burst","overlap","first"):
            src,dest=(100,100),(118,102)
            if case=="near_bottom":src,dest=(100,320),(118,324)
            if case=="too_far":dest=(290,180)
            if case=="overlap":dest=(106,103)
            p,t,a,b=frames(surface,src,dest,noise if case=="noise" else None)
            known=Image.new("1",(320,312),0 if case=="unknown" else 1)
            if case=="one_unknown":known.putpixel((115,105),0)
            if case=="changed_gap":t.putpixel((115,105),(12,34))
            if case=="first":a=None
            expected=packets(renderer.pointer_updates(p,t,a,b))
            result=packets(renderer.pointer_updates(p,t,a,b,exact=known,burst=1 if case=="no_burst" else 8))
            self.assertEqual(result,expected,case)

    def test_service_admits_only_after_lossless_ack_and_discards_provenance_after_jpeg(self):
        class Done(Exception):pass
        desk=LANDSCAPE
        plain=Image.new("RGB",desk,"#123456")
        lighter=plain.copy()
        lighter.paste("#778899",(50,50,220,148))
        loud=Image.new("RGB",desk,"#4d0011")
        images=[fit_frame(im,native=True,surface=desk) for im in (plain,lighter,loud)]
        indices=[0,0,1,1,2,2]
        spots=[100,118,118,136,136,154]
        class Worker:
            ident=0
            source=SimpleNamespace(surface=desk)
            stop=threading.Event()
            def snapshot(self):
                f,v=images[indices[self.ident]]
                position=(round(spots[self.ident]*65534/(desk[0]-1)),round(100*65534/(desk[1]-1)))
                return self.ident,f,replace(v,pointer=position)
        worker=Worker()
        peer=Receiver(self,worker,lambda *_:None)
        actual=renderer.try_cursor_union
        decisions={}
        def measure(p,t,boxes,separate,exact,burst):
            chosen=actual(p,t,boxes,separate,exact,burst)
            decisions[worker.ident]=chosen is not separate
            return chosen
        def plans(current,target,start,force,caps,**kwargs):
            if worker.ident in (0,4):
                return [(0,jpeg_scene(kwargs["jpeg_background"]))]
            return zlib_updates(current,target,(50,50,220,148))
        def notice(kind,value):
            if kind=="paint" and value==worker.ident:
                if value==5:raise Done()
                worker.ident+=1
        with patch.object(renderer,"try_cursor_union",side_effect=measure),patch.object(renderer,"select_plan",side_effect=plans):
            with self.assertRaises(Done):
                renderer.serve(None,worker,3,link_factory=peer.start,notice=notice,direct_usb=True)
        self.assertEqual(decisions,{1:False,3:True,5:False})


if __name__=="__main__":
    unittest.main()
