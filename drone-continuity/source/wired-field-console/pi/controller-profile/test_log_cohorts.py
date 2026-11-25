"""Offline source attribution against the production analyzer using only synthetic reports."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def stat(value, count=1):
    return dict(count=count,minimum=value,maximum=value,mean=value,m2=0)


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        stubs={'flight_efficiency_metrics':types.SimpleNamespace(FlightEfficiencyMetrics=object),
               'battery_profile_store':types.SimpleNamespace(summary=lambda *a,**k:{})}
        with patch.dict(sys.modules,stubs):
            source=os.environ.get('CORVON_ANALYZER_SOURCE',Path(__file__).with_name('orangepi-bin-analyzer'))
            self.mod=runpy.run_path(str(source))
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('create table logs(sha256 text primary key, report_path text)')
        env=self.mod['rebuild_profile'].__globals__
        env['PROFILE']=self.root/'profiles'
        env['ROOT']=self.root

    def report(self,index,board,reading,*,version=(4,7,3),vehicle=2,board_type=10):
        digest=hashlib.sha256(str(index).encode()).hexdigest()
        keys=dict(zip(('APJ','BT','BU','Maj','Min','Pat'),(board,board_type,vehicle,*version)))
        fields={'VER.'+key:stat(value) for key,value in keys.items()}
        fields['TEST.health']=stat(reading)
        return {'source':{'sha256':digest,'bytes':4},'analysis':{'message_types':{'VER':1,'TEST':1},
                'numeric_fields':fields,'messages':2,'duration_seconds':2.5}}

    def add(self,report,digest=None):
        sha=digest or report['source']['sha256']
        path=self.root/(sha+'.json')
        path.write_text(json.dumps(report))
        self.db.execute('insert into logs values (?,?)',(sha,str(path)))
        return sha

    def test_shuffled_mixed_versions_instances_and_missing_identity(self):
        target=self.mod['CURRENT_GROUP']
        self.add(self.report(1,99,400))
        a=self.add(self.report(2,1229,0))
        self.add(self.report(3,1229,44,vehicle=1))
        self.add(self.report(4,1229,70,version=(4,7,2)))
        b=self.add(self.report(5,1229,4))
        self.add(self.report(6,1229,60,board_type=3))
        unassigned=self.report(7,1229,99)
        del unassigned['analysis']['numeric_fields']['VER.APJ']
        self.add(unassigned)
        mismatched_report=self.add(self.report(8,1229,900),'a'*64)
        summary=self.mod['rebuild_profile'](self.db)
        self.assertEqual(summary['files'],2)
        self.assertEqual(summary['numeric_fields']['TEST.health']['mean'],2.0)
        self.assertEqual(summary['controller_groups'][target],2)
        self.assertEqual(summary['controller_groups']['unassigned'],1)
        self.assertEqual(summary['controller_groups']['unverified-report'],1)
        self.assertEqual(summary['source_set_sha256'],hashlib.sha256(b''.join(bytes.fromhex(i) for i in sorted((a,b)))).hexdigest())
        membership=dict(self.db.execute('select sha256,controller_group from log_controller_groups'))
        self.assertEqual(membership[mismatched_report],'unverified-report')
        self.assertEqual({i for i,k in membership.items() if k==target},{a,b})
        corpus=json.loads((self.root/'profiles/all-boards.json').read_text())
        self.assertEqual(corpus['role'],'historical_inventory_all_boards')
        self.assertEqual(corpus['files'],7)
        second=self.mod['rebuild_profile'](self.db)
        self.assertEqual(second['source_set_sha256'],summary['source_set_sha256'])
        self.assertEqual(self.db.execute('select count(*) from log_controller_groups').fetchone()[0],8)

    def test_no_target_and_conflicting_or_incomplete_ver(self):
        for index,mode in enumerate(('conflict','missing','other','malformed','bool','version')):
            report=self.report(index,1229,100)
            stats=report['analysis']['numeric_fields']
            if mode=='conflict':stats['VER.APJ']['maximum']=1230
            elif mode=='missing':report['analysis']['message_types']['VER']=2
            elif mode=='other':stats['VER.APJ']=stat(99)
            elif mode=='malformed':stats['VER.APJ']=stat(1229.5)
            elif mode=='bool':stats['VER.APJ']=stat(True)
            else:del stats['VER.Min']
            self.add(report)
        result=self.mod['rebuild_profile'](self.db)
        self.assertEqual(result['files'],0)
        self.assertEqual(result['numeric_fields'],{})
        self.assertEqual(result['messages'],0)


if __name__=='__main__':
    unittest.main()
