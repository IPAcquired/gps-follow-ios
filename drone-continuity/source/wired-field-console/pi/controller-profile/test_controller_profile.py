import ast, math, sys, time, unittest
from pathlib import Path
from unittest.mock import Mock, patch
import controller_profile as profile
import display_telemetry

root=Path(__file__).resolve().parent
code=ast.parse((root/'orangepi-companion').read_text(encoding='utf8'))
names={'browser_owner_safe','live_flight_status','_advisory_number','sensor_observation_status'}
ns={'time':time,'math':math,'read_json':Mock(),'MAVLINK_STATUS':None,'controller_profile':profile.controller_profile,
    'source_pair':profile.source_pair,'device_exists':lambda *p:True}
exec(compile(ast.Module([n for n in code.body if isinstance(n,ast.FunctionDef) and n.name in names],[]),'companion','exec'),ns)

class ControllerTests(unittest.TestCase):
    def setUp(self):
        route=patch('controller_profile.verified_route',side_effect=lambda name:name=='/dev/ttyS0')
        route.start();self.addCleanup(route.stop)
        now=time.time()
        self.flight={'schema':1,'authority':'read_only_no_mavlink_transmit','updated_unix':now,'last_heartbeat_unix':now-.1,
            'connected':True,'fresh':True,'armed':False,'transport':'/dev/ttyS0','mode':'STABILIZE','h743_source':{'system_id':33,'component_id':1},
            'expected_source':{'system_id':33,'component_id':1}}
        ns['read_json'].return_value=self.flight
    def snapshot(self):
        return display_telemetry.build_snapshot(ns['live_flight_status'](),{}, {},pi={})
    def test_matched_source_configured_only(self):
        data=self.snapshot()
        self.assertEqual(data['schema'],1)
        self.assertEqual(data['controller_profile'],dict(configured_model='CORVON743V2',configured_board_id=1229,
                                                        source_state='matching',presence='heartbeat'))
        self.assertIs(data['h743']['armed']['value'],False)
        self.assertTrue(ns['browser_owner_safe']())
    def test_mismatch_is_observed_but_untrusted(self):
        self.flight['expected_source']['system_id']=34
        data=self.snapshot()
        self.assertEqual(data['controller_profile']['presence'],'heartbeat')
        self.assertEqual(data['controller_profile']['source_state'],'mismatch')
        self.assertIsNone(data['h743']['armed']['value'])
        self.assertFalse(ns['browser_owner_safe']())
        self.assertFalse(ns['sensor_observation_status'](ns['live_flight_status'](),{})[0]['flight_controller'])
    def test_missing_and_malformed_source_ids(self):
        for bad in (None,[],{}, {'system_id':True,'component_id':1},{'system_id':0,'component_id':1},
                    {'system_id':256,'component_id':1},{'system_id':33,'component_id':False}):
            with self.subTest(bad=bad):
                self.flight['expected_source']=bad
                self.assertFalse(ns['browser_owner_safe']())
                data=self.snapshot()
                self.assertEqual(data['controller_profile']['source_state'],'unverified')
                self.assertIsNone(data['h743']['armed']['value'])
    def test_stale_future_and_silent_do_not_prove_absence_or_disarm(self):
        now=time.time()
        for stamp in (None,now-2.1,now+3,float('nan')):
            self.flight['last_heartbeat_unix']=stamp
            self.assertFalse(ns['browser_owner_safe']())
            self.assertEqual(self.snapshot()['controller_profile']['presence'],'unknown')
        self.flight.update(connected=False,last_heartbeat_unix=None)
        self.assertFalse(ns['browser_owner_safe']())
        self.assertIsNone(self.snapshot()['h743']['armed']['value'])
    def test_armed_and_malformed_guard(self):
        for value in (True,None,0,'false'):
            self.flight['armed']=value
            self.assertFalse(ns['browser_owner_safe']())
        self.flight.update(armed=False,authority='wrong')
        self.assertFalse(ns['browser_owner_safe']())
        self.assertEqual(self.snapshot()['controller_profile']['source_state'],'unverified')
    def test_wrong_board_on_old_link_cannot_unlock_with_matching_mavlink_ids(self):
        for route,state in (('/dev/h743-usb','mismatch'),('/dev/rfcomm0','mismatch'),('/dev/ttyUSB0','unverified'),(None,'unverified')):
            self.flight['transport']=route
            self.assertFalse(ns['browser_owner_safe']())
            self.assertEqual(self.snapshot()['controller_profile']['source_state'],state)
            self.assertIsNone(self.snapshot()['h743']['armed']['value'])
    def test_board_source_and_wire_map(self):
        self.assertEqual(profile.board_reference()['source_status'],'verified_offline_copy')
        self.assertFalse(profile.board_reference()['live_firmware_bytes_attested'])
        self.assertEqual([profile.SENSOR_LINKS[k]['pi_port'] for k in ('flight_controller','rplidar','matrix_lidar','camera')],
                         ['UART0','UART2','UART7','USB'])
    def test_wrong_origin_secondary_fields(self):
        self.flight['battery']={'source_system_id':32,'source_component_id':1,'battery_id':0,
            'fresh':True,'voltage_v':22,'updated_unix':time.time(),'message_type':'SYS_STATUS'}
        self.assertIsNone(self.snapshot()['h743']['battery_voltage_v']['value'])
    def test_cross_source_invalidates_sensor_health(self):
        self.flight['h743_source']['component_id']=200
        data=display_telemetry.build_snapshot(self.flight,{'flight_controller':{'fresh':True,'status':'fresh_data'}},{},pi={})
        self.assertFalse(data['sensor_health']['flight_controller']['fresh'])

if __name__=='__main__':unittest.main()
