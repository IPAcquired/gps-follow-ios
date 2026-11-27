"""Exercise the production cache binding without opening a service or requesting a review."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest




class ReviewBinding(unittest.TestCase):
    def test_scope_empty_history_and_digest(self):
        root=Path(__file__).resolve().parent
        source=(root/'orangepi-companion').read_text(encoding='utf8')
        fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='current_log_review')
        ns={'json':json,'hashlib':hashlib}
        exec(compile(ast.Module([fn],[]),'test','exec'),ns)
        read=ns['current_log_review']
        with tempfile.TemporaryDirectory() as area:
            path=Path(area)/'current.json'
            profile={'files':1,'controller_group':'APJ-1229/BT-10/BU-2/4.7.3'}
            path.write_text(json.dumps(profile))
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            review=dict(schema=1,mode='live_jev_post_flight_review',real_jev_called=True,
                        source_profile_sha256=sha,profile_review_id='sha256:'+sha,
                        flight_control_authority=False,mavlink_transmit_enabled=False,
                        may_write_ardupilot_parameters=False,automatic_change_allowed=False)
            self.assertEqual(read(path,review),(profile,review))
            for key,new in [('source_profile_sha256','0'*64),('profile_review_id','sha256:'+'1'*64),
                            ('may_write_ardupilot_parameters',True),('schema',True)]:
                self.assertEqual(read(path,dict(review,**{key:new})),(profile,{}))
            path.write_bytes(path.read_bytes()+b'\n')
            self.assertEqual(read(path,review),(profile,{}))
            path.write_text(json.dumps(dict(profile,files=0)))
            self.assertEqual(read(path,review)[1],{})
            path.write_text(json.dumps({'files':10}))
            self.assertEqual(read(path,review),({},{}))

if __name__=='__main__':unittest.main()
