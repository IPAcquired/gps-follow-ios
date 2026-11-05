"""Exercise the real companion route methods without hardware or credentials."""
import ast
from http import HTTPStatus
from pathlib import Path
import secrets
import time
import types
import unittest
from unittest.mock import patch

source=ast.parse(Path(__file__).with_name('orangepi-companion').read_text())
handler=next(item for item in source.body if isinstance(item,ast.ClassDef) and item.name=='Handler')
methods=[item for item in handler.body if isinstance(item,ast.FunctionDef) and item.name in ('do_POST','phone_quick_connect')]
namespace={'HTTPStatus':HTTPStatus,'time':time,'secrets':secrets}
exec(compile(ast.Module(body=methods,type_ignores=[]),'actual_companion_methods','exec'),namespace)

class Fake:
    do_POST=namespace['do_POST']
    phone_quick_connect=namespace['phone_quick_connect']
    def __init__(self,authorized=True,ip='10.42.0.2',origin=None,body=None):
        self.path='/api/phone-quick-connect';self.client_address=(ip,1234)
        self.headers={'Content-Type':'application/json'}
        if origin:self.headers['Origin']=origin
        self.authorized=authorized;self.body={} if body is None else body;self.response=None
    def require_auth(self):
        if not self.authorized:self.send_json(401,{'error':'unauthorized'})
        return self.authorized
    def read_json(self,maximum):return self.body
    def send_json(self,code,value):self.response=(int(code),value)
    def send_error(self,code):self.response=(int(code),{})

class RouteTests(unittest.TestCase):
    def test_only_authenticated_display_post_can_issue(self):
        issued=[]
        def issue():issued.append(True);return {'ok':True}
        with patch.dict('sys.modules',{'quick_connect':types.SimpleNamespace(request_code=issue)}):
            for item,status in [(Fake(False),401),(Fake(ip='192.168.1.174'),403),
                                (Fake(origin='https://orangepi-drone.local'),403),
                                (Fake(body={'arm':True}),503),(Fake(),200)]:
                item.do_POST();self.assertEqual(item.response[0],status)
        self.assertEqual(len(issued),1)

    def test_get_never_issues_a_code(self):
        method=next(x for x in handler.body if isinstance(x,ast.FunctionDef) and x.name=='do_GET')
        self.assertFalse(any(isinstance(x,ast.Attribute) and x.attr=='phone_quick_connect' for x in ast.walk(method)))

if __name__=='__main__':unittest.main()
