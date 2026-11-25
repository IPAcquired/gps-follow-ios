import hashlib
import json
import threading
import time
import unittest
from unittest.mock import patch
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from follow_location import PhoneLocationStore
from phone_browser import PhoneAccess, handler_for


class PhoneBrowserTests(unittest.TestCase):
    def setUp(self):
        self.token='a'*64
        self.config={'expires_unix':time.time()+60,'token_sha256':hashlib.sha256(self.token.encode()).hexdigest()}
        self.store=PhoneLocationStore()
        self.access=PhoneAccess(self.config,self.store)

    def test_authentication_and_expiry(self):
        self.assertTrue(self.access.authorized('Bearer '+self.token))
        for token in (None,'','Bearer '+'b'*64,'bearer '+self.token,'Bearer '+self.token+'x'):
            self.assertFalse(self.access.authorized(token))
        self.config['expires_unix']=0
        self.assertFalse(self.access.authorized('Bearer '+self.token))

    def test_freshness_stop_and_no_flight_authority(self):
        with patch('time.monotonic',return_value=100):
            result=self.access.accept({'lat':0,'lon':0,'accuracy_m':5,'age_ms':10},'phone')
        self.assertEqual(result['provenance'],'authenticated_phone_browser')
        self.assertFalse(result['mavlink_transmit'])
        self.assertFalse(result['position_is_drone_gps'])
        with patch('time.monotonic',return_value=104):
            result=self.store.snapshot()
        self.assertEqual(result['status'],'stale')
        self.assertNotIn('lat',result)
        with patch('time.monotonic',return_value=105):
            self.assertEqual(self.access.accept({'stop':True},'phone')['status'],'stopped')

    def test_invalid_fix_and_extra_authority_rejected(self):
        for value in ({'lat':True,'lon':0,'accuracy_m':5,'age_ms':0},
                      {'lat':91,'lon':0,'accuracy_m':5,'age_ms':0},
                      {'lat':0,'lon':float('nan'),'accuracy_m':5,'age_ms':0},
                      {'lat':0,'lon':0,'accuracy_m':31,'age_ms':0},
                      {'lat':0,'lon':0,'accuracy_m':5,'age_ms':3000},
                      {'stop':True,'arm':True}):
            with self.assertRaises(ValueError):self.access.accept(value,'phone')
        self.assertEqual(self.store.snapshot()['status'],'unavailable')

    def test_rate_and_second_phone(self):
        self.access.accept({'stop':True},'first')
        with self.assertRaises(ValueError):self.access.accept({'stop':True},'first')
        with patch('time.monotonic',return_value=self.access.last+1):
            with self.assertRaises(ValueError):self.access.accept({'stop':True},'second')

    def test_return_from_native_gps_does_not_reuse_retired_epoch(self):
        fix={'lat':0,'lon':0,'accuracy_m':5,'age_ms':0}
        with patch('time.monotonic',return_value=100):
            self.access.accept(fix,'phone')
            old=self.access.epoch
        with patch('time.monotonic',return_value=101):
            self.store.accept(dict(fix,source='phone_gps',source_epoch='b'*32,seq=1))
        with patch('time.monotonic',return_value=102):
            with self.assertRaises(ValueError):self.access.accept(fix,'phone')
        with patch('time.monotonic',return_value=105):
            self.assertEqual(self.access.accept(fix,'phone')['status'],'fresh')
            self.assertNotEqual(self.access.epoch,old)

    def test_http_origin_scope_and_auth(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.access))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(path,headers):
            c=HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            c.request('POST',path,json.dumps({'stop':True}),headers)
            r=c.getresponse();r.read();status=r.status;c.close();return status
        headers={'Host':'example-pi.local:8445','Origin':'https://example-pi.local:8445','Content-Type':'application/json','Authorization':'Bearer '+self.token}
        try:
            self.assertEqual(call('/location',headers),200)
            self.assertEqual(call('/api/input',headers),404)
            self.assertEqual(call('/api/updates',headers),404)
            self.assertEqual(call('/location',dict(headers,Origin='https://evil.invalid')),403)
            self.assertEqual(call('/location',dict(headers,Authorization='Bearer '+'b'*64)),401)
            self.assertEqual(call('/location',dict(headers,Host='evil.invalid')),403)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
