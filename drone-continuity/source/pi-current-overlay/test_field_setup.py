import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import random
import threading
import time
import unittest
from unittest.mock import patch, Mock
import tempfile
from pathlib import Path
import field_wifi
from field_setup import handler_for
from quick_connect import PairingCodes


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.token='a'*64
        self.config={'expires_unix':time.time()+60,'token_sha256':hashlib.sha256(self.token.encode()).hexdigest()}
        self.codes=PairingCodes(self.config["expires_unix"])
        self.calls=[]
        def dispatch(value):
            self.calls.append(value)
            return {'ok':True}
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.config,codes=self.codes,dispatch=dispatch,snapshot=lambda:{'schema':1,'flight_control_authority':False,'h743':{'connected':{'fresh':False,'value':None}}}))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def call(self,path,body=b'{}',headers=None):
        base={'Host':'example-pi.local:8446','Origin':'https://example-pi.local:8446',
              'Authorization':'Bearer '+self.token,'Content-Type':'application/json'}
        base.update(headers or {})
        connection=HTTPConnection(*self.server.server_address,timeout=2)
        connection.request('POST',path,body,base)
        response=connection.getresponse();result=response.status,dict(response.headers),response.read()
        connection.close();return result

    def test_capability_origin_and_expiry(self):
        self.assertEqual(self.call('/status',headers={'Authorization':'Bearer '+'b'*64})[0],401)
        self.assertEqual(self.call('/status',headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.call('/status',headers={'Host':'evil.invalid'})[0],403)
        self.config['expires_unix']=0
        self.assertEqual(self.call('/status')[0],401)
        self.assertEqual(self.calls,[])

    def test_scope_and_bounded_body(self):
        for path in ('/location','/api/input','/api/owner/access','/api/update','/../etc/passwd'):
            self.assertEqual(self.call(path)[0],404)
        for body in (b'[]',b'null',b'{"arm":true}',b' '*513):
            self.assertEqual(self.call('/hotspot',body)[0],422)
        self.assertEqual(self.calls,[])

    def test_valid_save_rate_and_no_secrets_in_response(self):
        payload=b'{"ssid":"Phone test","password":"test-only-secret"}'
        status,headers,body=self.call('/hotspot',payload)
        self.assertEqual(status,200);self.assertNotIn(b'test-only-secret',body)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(self.calls[0]['action'],'save_hotspot')
        self.assertEqual(self.call('/hotspot',payload)[0],429)

    def test_session_cookie_is_private_scoped_and_revoked(self):
        status,headers,body=self.call('/session')
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'];self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=Strict',cookie);self.assertNotIn(self.token,cookie)
        headers={'Authorization':'','Cookie':cookie.split(';')[0]}
        self.assertEqual(self.call('/status',headers=headers)[0],200)
        self.assertEqual(self.call('/session',headers=headers)[0],401)
        self.assertEqual(self.call('/status',headers=dict(headers,Origin='https://evil.invalid'))[0],403)
        self.assertEqual(self.call('/logout',headers=headers)[0],200)
        self.assertEqual(self.call('/status',headers=headers)[0],401)

    def test_snapshot_requires_owner_access_and_accepts_no_commands(self):
        self.assertEqual(self.call('/telemetry',headers={'Authorization':''})[0],401)
        self.assertEqual(self.call('/telemetry',b'{"arm":true}')[0],422)
        status,_,body=self.call('/telemetry');self.assertEqual(status,200)
        self.assertFalse(json.loads(body)['snapshot']['flight_control_authority'])
        self.assertEqual(self.calls,[])

    def test_review_does_not_modify_network(self):
        self.assertTrue(json.loads(self.call('/status')[2])['review_required'])
        self.assertFalse(json.loads(self.call('/review')[2])['network_changed'])
        self.assertFalse(json.loads(self.call('/status')[2])['review_required'])
        self.assertTrue(all(item['action']=='status' for item in self.calls))

    def test_qr_pairing_single_use_no_owner_secret(self):
        issued=self.codes.issue();code=issued['url'].split('#join=')[1]
        self.assertNotIn(self.token,issued['url'])
        status,headers,_=self.call('/pair',json.dumps({'code':code}).encode(),{'Authorization':''})
        self.assertEqual(status,200);cookie=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.call('/telemetry',headers={'Authorization':'','Cookie':cookie})[0],200)
        self.assertEqual(self.call('/pair',json.dumps({'code':code}).encode(),{'Authorization':''})[0],401)
        self.assertEqual(self.calls,[])

    def test_qr_cross_origin_and_malformed_request_do_not_consume(self):
        code=self.codes.issue()['url'].split('#join=')[1];body=json.dumps({'code':code}).encode()
        self.assertEqual(self.call('/pair',body,{'Authorization':'','Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.call('/pair',b'{}',{'Authorization':''})[0],422)
        self.assertEqual(self.call('/pair',body,{'Authorization':''})[0],200)

    def test_capability_expiry_also_expires_existing_session(self):
        _,headers,_=self.call('/session');cookie=headers['Set-Cookie'].split(';')[0]
        self.config['expires_unix']=0
        self.assertEqual(self.call('/telemetry',headers={'Authorization':'','Cookie':cookie})[0],401)


class GuardTests(unittest.TestCase):
    def baseline(self):
        return dict(schema=1,authority='read_only_no_mavlink_transmit',armed=False,connected=False,
                    reason='opening_transport',last_heartbeat_unix=None,flight_session_id=None,updated_unix=100)

    def test_10000_seeded_guard_cases(self):
        randomizer=random.Random(74332)
        choices=[None,True,False,'false',float('nan'),float('inf'),-10,0,96,100,101]
        for _ in range(10000):
            value=self.baseline()
            value['armed']=randomizer.choice(choices)
            value['updated_unix']=randomizer.choice(choices)
            expected=(value['armed'] is False and type(value['updated_unix']) in (int,float)
                      and 97<=value['updated_unix']<=100)
            self.assertEqual(field_wifi.safe_flight(value,100),expected)

    def test_lost_link_never_allows_activation(self):
        value=self.baseline();value['schema']=True
        self.assertFalse(field_wifi.safe_flight(value,100))
        value=self.baseline();value.update(reason='heartbeat_timeout',last_heartbeat_unix=90)
        self.assertFalse(field_wifi.safe_flight(value,100))
        value=self.baseline();value['flight_session_id']='previous-flight'
        self.assertFalse(field_wifi.safe_flight(value,100))
        value=self.baseline();value.update(connected=True,heartbeat_updated_unix=99)
        self.assertTrue(field_wifi.safe_flight(value,100))
        value['heartbeat_updated_unix']=97
        self.assertFalse(field_wifi.safe_flight(value,100))

    def test_online_station_is_not_reconfigured(self):
        with tempfile.TemporaryDirectory() as folder:
            pending=Path(folder)/'pending';pending.write_text('{}')
            wifi=Mock();wifi.wpa_status.return_value={'state':'COMPLETED'}
            with patch.object(field_wifi,'PENDING',pending):
                self.assertEqual(field_wifi.apply_pending(wifi),'waiting_for_upstream_disconnect')
            wifi.netplan_generate.assert_not_called();wifi.wpa.assert_not_called()

    def test_save_has_no_live_network_mutations(self):
        wifi=Mock();wifi.validate_ssid.return_value='Test Phone';wifi.validate_password.return_value='test-only-password'
        wifi.load_config.return_value=({}, {})
        with patch.object(field_wifi,'load_private',return_value={}):
            result=field_wifi.dispatch({'action':'save_hotspot','ssid':'Test Phone','password':'test-only-password'},wifi)
        self.assertFalse(result['current_connection_changed'])
        stored=json.loads(wifi.atomic_write.call_args.args[1]);self.assertEqual(len(stored['psk']),64)
        self.assertNotIn('test-only-password',json.dumps(stored))
        wifi.netplan_generate.assert_not_called();wifi.wpa.assert_not_called()

    def test_existing_home_profile_is_not_overwritten(self):
        wifi=Mock();wifi.validate_ssid.return_value='Home';wifi.validate_password.return_value='test-only-password'
        wifi.load_config.return_value=({}, {'Home':{}})
        with patch.object(field_wifi,'load_private',return_value={}):
            with self.assertRaises(ValueError):
                field_wifi.dispatch({'action':'save_hotspot','ssid':'Home','password':'test-only-password'},wifi)
        wifi.atomic_write.assert_not_called()

    def test_activation_and_rollback(self):
        for accepted in (True,False):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as folder:
                folder=Path(folder); pending=folder/'pending.json';managed=folder/'managed.json'
                pending.write_text(json.dumps({'ssid':'Test Phone','psk':'a'*64}))
                config=folder/'config.yaml';config.write_text('original')
                wifi=Mock();wifi.CONFIG=config;wifi.RUNTIME=folder
                wifi.wpa_status.return_value={'state':'DISCONNECTED'}
                wifi.validate_ssid.side_effect=lambda value:value
                wifi.load_config.return_value=({'network':{}},{})
                wifi.atomic_write.side_effect=lambda path,data:path.write_bytes(data)
                wifi.wpa.side_effect=['OK','OK'] if accepted else ['FAIL','OK']
                with patch.object(field_wifi,'STATE',folder),patch.object(field_wifi,'PENDING',pending),patch.object(field_wifi,'MANAGED',managed),patch.object(field_wifi,'read_flight_status',return_value=self.baseline()),patch.object(field_wifi.time,'time',return_value=100),patch.object(field_wifi,'load_private',side_effect=lambda path,default=None:json.loads(path.read_text()) if path.exists() else default):
                    if accepted:
                        self.assertEqual(field_wifi.apply_pending(wifi),'profile_loaded')
                        self.assertFalse(pending.exists());self.assertTrue(managed.exists())
                        self.assertEqual([call.args[0] for call in wifi.wpa.call_args_list],['RECONFIGURE','ENABLE_NETWORK all'])
                    else:
                        with self.assertRaises(ValueError):field_wifi.apply_pending(wifi)
                        self.assertEqual(config.read_text(),'original');self.assertTrue(pending.exists())

    def test_queued_connection_rejects_unsaved_and_unsafe_networks(self):
        wifi=Mock();wifi.validate_ssid.side_effect=lambda x:x;wifi.load_config.return_value=({}, {'Home':{'password':'x'}})
        with patch.object(field_wifi,'load_private',return_value={}):
            with self.assertRaises(ValueError):field_wifi.dispatch({'action':'request_connect','ssid':'Open network'},wifi)
            with patch.object(field_wifi,'read_flight_status',return_value={}):
                with self.assertRaises(ValueError):field_wifi.dispatch({'action':'request_connect','ssid':'Home'},wifi)
        wifi.atomic_write.assert_not_called();wifi.wpa.assert_not_called()

    def test_failed_saved_connection_restores_home_and_all_profiles(self):
        wifi=Mock();wifi.validate_ssid.side_effect=lambda x:x;wifi.network_ids.return_value={'Home':'0','Phone':'1'}
        wifi.wpa_status.return_value={'ssid':'Home','state':'COMPLETED','ip':'192.168.1.2'};wifi.wpa.return_value='OK'
        with tempfile.TemporaryDirectory() as directory:
            connect=Path(directory)/'connect';connect.write_text('{}')
            with patch.object(field_wifi,'CONNECT',connect),patch.object(field_wifi,'load_private',side_effect=lambda p,default=None:{'ssid':'Phone'} if p==connect else {}),patch.object(field_wifi,'read_flight_status',return_value=self.baseline()),patch.object(field_wifi.time,'time',return_value=100),patch.object(field_wifi.time,'monotonic',side_effect=[0,100]):
                self.assertEqual(field_wifi.apply_requested_connection(wifi),'failed')
        self.assertEqual([c.args[0] for c in wifi.wpa.call_args_list],['SELECT_NETWORK 1','SELECT_NETWORK 0','ENABLE_NETWORK all'])


if __name__=='__main__':unittest.main()
