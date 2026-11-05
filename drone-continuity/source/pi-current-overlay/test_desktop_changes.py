import unittest,struct
import desktop_capture as d
def rows(payload):
 result=[];pos=0
 while True:
  row=struct.unpack_from('<H',payload,pos)[0];pos+=2
  if row==65535:break
  size=struct.unpack_from('<H',payload,pos)[0];pos+=2
  assert size>0 and pos+size<=len(payload);pos+=size;result.append(row)
 assert pos==len(payload)
 return result
class ChangedDesktopTests(unittest.TestCase):
 def setUp(self):d._frames.clear()
 def test_first_frame_complete_then_unchanged_has_no_pixels(self):
  raw=b'\x01\x02'*(32*8);payload,identity=d.changed_rows(raw,32,8,(0,0,10000,10000))
  self.assertEqual(rows(payload),list(range(8)))
  payload,next_id=d.changed_rows(raw,32,8,(0,0,10000,10000),identity)
  self.assertEqual(payload,b'\xff\xff');self.assertEqual(identity,next_id)
 def test_one_changed_row(self):
  raw=bytes(32*8*2);_,identity=d.changed_rows(raw,32,8,(0,0,10000,10000))
  changed=bytearray(raw);changed[32*2*3+4]=1
  payload,next_id=d.changed_rows(bytes(changed),32,8,(0,0,10000,10000),identity)
  self.assertEqual(rows(payload),[3]);self.assertNotEqual(next_id,identity)
 def test_missing_base_recovers_complete_frame(self):
  payload,_=d.changed_rows(bytes(512),32,8,(0,0,10000,10000),'f'*32)
  self.assertEqual(rows(payload),list(range(8)))
 def test_new_view_recovers_complete_frame(self):
  raw=bytes(512);_,identity=d.changed_rows(raw,32,8,(0,0,10000,10000))
  payload,next_id=d.changed_rows(raw,32,8,(0,0,5000,10000),identity)
  self.assertEqual(rows(payload),list(range(8)));self.assertNotEqual(next_id,identity)
 def test_cache_bounded_and_eviction_recovers(self):
  _,first=d.changed_rows(bytes(512),32,8,(0,0,10000,10000))
  for n in range(1,8):d.changed_rows(bytes([n])*512,32,8,(0,0,10000,10000))
  self.assertEqual(len(d._frames),3)
  payload,_=d.changed_rows(bytes(512),32,8,(0,0,10000,10000),first)
  self.assertEqual(rows(payload),list(range(8)))
