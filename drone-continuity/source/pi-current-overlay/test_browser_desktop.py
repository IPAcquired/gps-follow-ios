import unittest,time,hashlib,json,threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from browser_desktop import DesktopOwner,validate_input
from wifi_snapshot import WifiSnapshot
from field_setup import handler_for

class OwnerTests(unittest.TestCase):
 def setUp(self):
  self.now=10.;self.safe=True;self.actions=[]
  self.owner=DesktopOwner(lambda:self.safe,lambda:(b'test-jpeg',960,720),self.actions.append,lambda:self.now)
  self.key='1'*64
 def call(self,action,**extra):return self.owner.handle(dict(extra,owner=self.key,action=action))
 def test_unlock_expiry_and_no_implicit_authority(self):
  with self.assertRaises(PermissionError):self.call('frame')
  self.call('unlock');self.assertIn('jpeg',self.call('frame'))
  self.now+=300
  with self.assertRaises(PermissionError):self.call('frame')
  self.assertEqual(self.actions,[])
 def test_guard_revokes_existing_owner(self):
  self.call('unlock');self.safe=False
  with self.assertRaises(PermissionError):self.call('input',event_id=1,command={'type':'key','key':'enter'})
  self.safe=True
  with self.assertRaises(PermissionError):self.call('frame')
  self.assertEqual(self.actions,[])
 def test_replay_separation_and_lock(self):
  self.call('unlock');command={'type':'tap','x':0,'y':10000,'button':'left'}
  self.call('input',event_id=1,command=command);self.assertEqual(self.actions,[command])
  self.now+=1
  with self.assertRaises(ValueError):self.call('input',event_id=1,command=command)
  with self.assertRaises(PermissionError):self.owner.handle({'owner':'2'*64,'action':'frame'})
  frame=self.call('frame');self.assertNotIn('jpeg',self.call('frame',base=frame['frame_id']))
  self.call('lock')
  with self.assertRaises(PermissionError):self.call('frame')
 def test_invalid_commands_never_execute(self):
  self.call('unlock')
  for command in (None,{'type':'shell','command':'anything'},{'type':'tap','x':True,'y':0,'button':'left'},{'type':'key','key':'super+terminal'},{'type':'text','text':'x'*257},{'type':'scroll','dy':9},{'type':'drag','x':0,'y':0,'end_x':10001,'end_y':0}):
   with self.assertRaises(ValueError):self.call('input',event_id=1,command=command)
  self.assertEqual(self.actions,[])
 def test_10000_bounded_pointer_variants(self):
  for n in range(10000):
   x=(n*53)%12000-1000;y=(n*71)%12000-1000
   command={'type':'tap','x':x,'y':y,'button':'left'}
   if 0<=x<=10000 and 0<=y<=10000:self.assertEqual(validate_input(command),command)
   else:
    with self.assertRaises(ValueError):validate_input(command)

class WifiTests(unittest.TestCase):
 def test_observation_age_expiry_and_copy(self):
  now=[10.];cache=WifiSnapshot(lambda:now[0]);self.assertEqual(cache.read(),{})
  cache.sample(lambda:{'current':{'ssid':'test'}});now[0]+=1.25
  value=cache.read();self.assertEqual(value['_age_ms'],1250);value['current']['ssid']='changed';self.assertEqual(cache.read()['current']['ssid'],'test')
  now[0]+=3;self.assertEqual(cache.read(),{})
  cache.sample(lambda:(_ for _ in ()).throw(OSError()));self.assertEqual(cache.read(),{})

class BrowserRoutes(unittest.TestCase):
 def setUp(self):
  self.token='a'*64;self.calls=[];self.block=threading.Event();self.entered=threading.Event()
  def dispatch(v):
   if v['action']=='status':self.entered.set();self.block.wait(2)
   return {'ok':True}
  def desktop(v):self.calls.append(v);return {'ok':True}
  self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for({'expires_unix':time.time()+60,'token_sha256':hashlib.sha256(self.token.encode()).hexdigest()},dispatch=dispatch,snapshot=lambda:{'schema':1},desktop=desktop))
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.block.set();self.server.shutdown();self.server.server_close();self.thread.join()
 def call(self,path,value=None,cookie=None,origin='https://orangepi-drone.local:8446'):
  headers={'Host':'orangepi-drone.local:8446','Origin':origin,'Content-Type':'application/json'}
  if cookie is None:headers['Authorization']='Bearer '+self.token
  else:headers['Cookie']=cookie
  c=HTTPConnection(*self.server.server_address,timeout=3);c.request('POST',path,json.dumps(value or {}),headers);r=c.getresponse();result=r.status,dict(r.headers),r.read();c.close();return result
 def test_desktop_requires_session_cookie_and_explicit_confirmation(self):
  self.assertEqual(self.call('/desktop/unlock',{'confirm':True})[0],401)
  cookie=self.call('/session')[1]['Set-Cookie'].split(';')[0]
  self.assertEqual(self.call('/desktop/unlock',{'confirm':False},cookie)[0],422)
  self.assertEqual(self.call('/desktop/unlock',{'confirm':True},cookie,origin='https://bad.invalid')[0],403)
  self.assertEqual(self.call('/desktop/unlock',{'confirm':True},cookie)[0],200)
  self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0]['action'],'unlock');self.assertEqual(len(self.calls[0]['owner']),64)
  self.call('/logout',cookie=cookie)
  self.assertEqual(self.call('/desktop/frame',{'base':''},cookie)[0],401)
 def test_telemetry_not_blocked_by_wifi_query(self):
  worker=threading.Thread(target=lambda:self.call('/status'));worker.start();self.assertTrue(self.entered.wait(1))
  began=time.monotonic();self.assertEqual(self.call('/telemetry')[0],200);self.assertLess(time.monotonic()-began,.5)
  self.block.set();worker.join()

if __name__=='__main__':unittest.main()
