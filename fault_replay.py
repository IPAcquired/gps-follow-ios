"""Deterministic read-only failed-service display replay. No systemctl, device, or clock changes."""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

def probe(path,gap):
    spec=importlib.util.spec_from_file_location("service_clock",path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    clock={"wall":10000.0,"mono":100.0}
    tasks=[]
    units=[]
    def tick(sec):
        clock["wall"]+=sec
        clock["mono"]+=sec
    m.time=SimpleNamespace(time=lambda:clock["wall"],monotonic=lambda:clock["mono"])
    m.threading=SimpleNamespace(Thread=lambda *,target,**k:SimpleNamespace(start=lambda:tasks.append(target)))
    def collect():
        observed=list(units)
        tick(2.)
        return observed,True
    m.sample_failed_services=collect
    def read():
        raw=m.service_faults(clock["wall"])
        view=m.build_snapshot({}, {}, {}, now=clock["wall"],pi={},services=raw)["pi_service_health"]
        # ESP's actual first freshness gate at zero extra transport latency.
        visible=view["fresh"] and view["sample_succeeded"] and view["age_ms"] is not None and view["age_ms"]<=15000
        return {"age_ms":view["age_ms"],"visible":visible,"units":view["units"] if visible else [],"pending_queries":len(tasks)}
    assert not read()["visible"]
    tasks.pop(0)()
    after=read()
    clock["wall"]+=gap
    tick(3)
    after_step=read()
    units.append("user:example-status.service")
    tick(6)
    due=read()
    if tasks:tasks.pop(0)()
    delivered=read()
    return dict(after_query=after,after_clock_step=after_step,refresh_due=due,changed_service=delivered)

def main(a):
    sys.path.insert(0,str(a.dependencies or a.stock.resolve().parent))
    shifts=[-691,0,691]
    if a.reverse:shifts=shifts[::-1]
    result={}
    for shift in shifts:
        pair={name:probe(path,shift) for name,path in (("stock",a.stock),("candidate",a.candidate))}
        new=pair["candidate"]
        assert new["after_query"]["age_ms"]==2000 and new["after_clock_step"]["age_ms"]==5000
        assert new["after_clock_step"]["visible"] and new["refresh_due"]["pending_queries"]==1
        assert new["changed_service"]["units"]==["user:example-status.service"]
        if shift<0:
            assert not pair["stock"]["after_clock_step"]["visible"] and not pair["stock"]["refresh_due"]["pending_queries"]
        result[str(shift)]=pair
    report={"sha256":{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in (("stock",a.stock),("candidate",a.candidate))},
            "observations":result,"method":"synthetic clocks and system/user list enumeration; production compact publisher; source-matched ESP service eligibility conditions, zero wire delay"}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report["sha256"]))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--stock",required=True,type=Path);p.add_argument("--candidate",required=True,type=Path);p.add_argument("--out",required=True,type=Path);p.add_argument("--dependencies",type=Path);p.add_argument("--reverse",action="store_true");main(p.parse_args())

