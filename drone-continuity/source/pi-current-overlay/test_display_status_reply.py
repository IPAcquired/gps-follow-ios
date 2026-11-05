import ast,pathlib,unittest
from http import HTTPStatus
source=ast.parse(pathlib.Path(__file__).with_name('orangepi-companion').read_text(encoding='utf-8'))
fn=next(x for x in source.body if isinstance(x,ast.FunctionDef) and x.name=='deterministic_chat_reply')
namespace={};exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual_status_advisory','exec'),namespace)
reply=namespace['deterministic_chat_reply']
handler=next(x for x in source.body if isinstance(x,ast.ClassDef) and x.name=='Handler')
proxy=next(x for x in handler.body if isinstance(x,ast.FunctionDef) and x.name=='proxy_chat')
def unrelated_inventory():raise AssertionError('STATUS must not wait on unrelated inventory')
namespace.update(HTTPStatus=HTTPStatus,system_status=unrelated_inventory)
exec(compile(ast.Module(body=[proxy],type_ignores=[]),'actual_chat_handler','exec'),namespace)
class FakeRequest:
    proxy_chat=namespace['proxy_chat']
    message='What is my current flight status?'
    def read_json(self):return {'message':self.message}
    def send_json(self,status,body):self.result=(status,body)
class StatusReplyTests(unittest.TestCase):
    def test_exact_display_button_offline_does_not_need_model(self):
        answer=reply('What is my current flight status?',{'flight':{'connected':False}})
        self.assertIn('No fresh H743 heartbeat',answer)
    def test_fresh_status_reads_known_mode_and_armed_state(self):
        answer=reply('What is my current flight status?',{'flight':{'connected':True,'mode':'STABILIZE','armed':False}})
        self.assertIn('STABILIZE',answer);self.assertIn('disarmed',answer)
    def test_unknown_armed_state_not_called_disarmed(self):
        answer=reply('What is my current flight status?',{'flight':{'connected':True,'mode':'UNKNOWN'}})
        self.assertIn('armed state unknown',answer)
    def test_action_guard_still_takes_precedence(self):
        answer=reply('Arm the drone and give flight status',{})
        self.assertIn('will not execute',answer)
    def test_actual_status_route_avoids_unrelated_inventory_and_model(self):
        for flight in ({'connected':False},{'connected':True,'armed':False,'mode':'STABILIZE'}):
            namespace['live_flight_status']=lambda:flight
            request=FakeRequest();request.proxy_chat()
            self.assertEqual(request.result[0],200)
            self.assertEqual(request.result[1]['model'],'deterministic-safety-guard')
            self.assertEqual(request.result[1]['authority'],'advisory_only')
    def test_learning_fast_route(self):
        namespace['learning_review_status']=lambda:{'waiting_for_human_review':2,'total_candidates':3,'weight_training':{}}
        request=FakeRequest();request.message='How is offline learning configured?';request.proxy_chat()
        self.assertEqual(request.result[0],200)
        self.assertIn('2 waiting for review / 3',request.result[1]['answer'])
        self.assertIn('No battery-model weight update',request.result[1]['answer'])
    def test_sensors_fast_route(self):
        namespace['live_flight_status']=lambda:{}
        namespace['vision_status']=lambda:{}
        namespace['sensor_observation_status']=lambda f,v:({'flight_controller':True,'camera':False},{},{})
        request=FakeRequest();request.message='Which sensors are reporting verified data?';request.proxy_chat()
        self.assertEqual(request.result[0],200)
        self.assertIn('Fresh verified data: H743.',request.result[1]['answer'])
    def test_learning_missing_evidence(self):
        for value in (None,[], 'broken'):
            self.assertIn('unavailable',reply('How is offline learning configured?',{'learning_review':value}))
if __name__=='__main__':unittest.main()
