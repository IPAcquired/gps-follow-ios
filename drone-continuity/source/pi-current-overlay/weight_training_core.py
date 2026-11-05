"""Offline training primitives. JSON/safetensors only; no flight-control authority."""
import hashlib
import json
import math
import os
from pathlib import Path
import random
import socket
import tempfile
import time

ROOT = Path.home()/'.local/share/orangepi-weight-training'
HEX = set('0123456789abcdef')
MAX_BYTES = 64*1024*1024

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def sha_file(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()

def valid_hash(value):return isinstance(value,str) and len(value)==64 and set(value)<=HEX

def atomic(path,value,immutable=False):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    if immutable:
        # A crash must not expose a partly written immutable candidate.
        fd,temp=tempfile.mkstemp(prefix='.weights-pending-',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            try:os.link(temp,path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes()!=raw:raise ValueError('Immutable artifact mismatch')
        finally:
            if os.path.exists(temp):os.unlink(temp)
    else:
        fd,temp=tempfile.mkstemp(prefix='.weights-',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    directory=os.open(path.parent,os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)

def read(path,default=None):
    if not path.is_file():return default
    if path.is_symlink() or path.stat().st_size>MAX_BYTES:raise ValueError('Invalid artifact')
    return json.loads(path.read_text())

def rows(paths,kind):
    if kind not in ('neural','qwen'):raise ValueError('Unknown training data kind')
    result=[];identities=set()
    for path in sorted(set(paths)):
        if path.is_symlink() or path.stat().st_size>MAX_BYTES:raise ValueError('Invalid training input file')
        with path.open() as source:
            while line:=source.readline(16385):
                if len(line)>16384:raise ValueError('Training record too large')
                if not line.strip():continue
                item=json.loads(line)
                if not isinstance(item,dict):raise ValueError('Training record must be an object')
                if item.get('synthetic') is not False or item.get('label_source')!='human_reviewed':
                    raise ValueError('Only explicitly non-synthetic human-reviewed labels can train production candidates')
                for key in ('flight_log_sha256','software_sha256','sensor_calibration_sha256'):
                    if not valid_hash(item.get(key)):raise ValueError('Missing flight/build/calibration provenance')
                timestamp=item.get('observed_unix')
                if type(timestamp) not in (int,float) or not math.isfinite(timestamp) or timestamp<=0:raise ValueError('Invalid observation timestamp')
                if kind=='neural':
                    features(item)
                    if type(item.get('required_avoid')) is not bool:raise ValueError('Avoidance labels must be reviewed booleans')
                else:
                    for key in ('prompt','answer'):
                        value=item.get(key)
                        if not isinstance(value,str) or not 1<=len(value)<=4000 or '\0' in value:raise ValueError('Reviewed Qwen prompt/answer required')
                identity=digest(item)
                if identity in identities:raise ValueError('Duplicate observation cannot inflate training support')
                identities.add(identity);result.append(item)
                if len(result)>100000:raise ValueError('Per-job 100k-record memory budget exceeded; retained files are not deleted')
    return result

def split(items):
    flights={}
    for item in items:flights.setdefault(item['flight_log_sha256'],[]).append(item)
    if len(flights)<3:raise ValueError('Need reviewed examples from at least three completed flights')
    ordered=sorted(flights,key=lambda key:max(v['observed_unix'] for v in flights[key]))
    heldout=set(ordered[-max(1,len(ordered)//5):])
    training=[v for key in ordered if key not in heldout for v in flights[key]]
    validation=[v for key in ordered if key in heldout for v in flights[key]]
    if len(training)<80 or len(validation)<20:raise ValueError('Need at least 80 training and 20 whole-flight held-out examples')
    return training,validation,sorted(heldout)

def features(item):
    distance=item.get('distance_mm');closing=item.get('closing_speed_mm_s')
    if type(distance) not in (int,float) or type(closing) not in (int,float):raise ValueError('Invalid numeric features')
    if not math.isfinite(distance) or not math.isfinite(closing) or not 50<=distance<=12000 or not 0<=closing<=50000:raise ValueError('Features outside validated bounds')
    return [1-distance/12000,min(closing/5000,1),min(closing/distance,5)/5]

def initial(seed=743):
    rng=random.Random(seed)
    return {'schema':1,'architecture':'mlp_3_8_1_tanh_sigmoid','role':'companion_advisory_only','flight_authority':False,
            'w1':[[rng.uniform(-.3,.3) for _ in range(3)] for _ in range(8)],'b1':[0.]*8,'w2':[rng.uniform(-.3,.3) for _ in range(8)],'b2':0.}

def validate_model(model):
    if not isinstance(model,dict) or type(model.get('schema')) is not int or model['schema']!=1 or model.get('architecture')!='mlp_3_8_1_tanh_sigmoid' or model.get('role')!='companion_advisory_only' or model.get('flight_authority') is not False:raise ValueError('Invalid neural authority/architecture')
    if len(model['w1'])!=8 or any(len(row)!=3 for row in model['w1']) or len(model['b1'])!=8 or len(model['w2'])!=8:raise ValueError('Invalid neural shape')
    values=[*model['b1'],*model['w2'],model['b2'],*[x for row in model['w1'] for x in row]]
    if any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>100 for x in values):raise ValueError('Invalid neural weights')
    return model

def forward(model,x):
    hidden=[math.tanh(sum(w*v for w,v in zip(row,x))+bias) for row,bias in zip(model['w1'],model['b1'])]
    z=sum(w*v for w,v in zip(model['w2'],hidden))+model['b2']
    return 1/(1+math.exp(-max(-40,min(40,z)))),hidden

def predict(model,item):return forward(validate_model(model),features(item))[0]

def evaluate(model,items):
    scores=[predict(model,item) for item in items]
    labels=[item['required_avoid'] for item in items]
    fn=sum(y and p<.5 for p,y in zip(scores,labels));fp=sum(not y and p>=.5 for p,y in zip(scores,labels))
    negatives=sum(not y for y in labels)
    return {'brier':sum((p-y)**2 for p,y in zip(scores,labels))/len(items),'false_negatives':fn,'false_positives':fp,'false_positive_rate':fp/max(1,negatives),'positives':sum(labels),'negatives':negatives,'samples':len(items)}

def fit(model,items,epochs=40,progress=lambda *args:None,guard=lambda:None):
    model=json.loads(json.dumps(validate_model(model)));before=digest(model);rng=random.Random(743)
    samples=[(features(item),float(item['required_avoid'])) for item in items]
    started=time.monotonic()
    for epoch in range(epochs):
        rng.shuffle(samples)
        for index,(x,y) in enumerate(samples):
            if index%256==0:
                guard()
                if time.monotonic()-started>180:raise RuntimeError('Training time budget reached; prior active weights retained')
            probability,hidden=forward(model,x);delta=probability-y;old=model['w2'][:];lr=.02
            for unit in range(8):
                model['w2'][unit]-=lr*delta*hidden[unit]
                gradient=delta*old[unit]*(1-hidden[unit]**2)
                model['b1'][unit]-=lr*gradient
                for col in range(3):model['w1'][unit][col]-=lr*gradient*x[col]
            model['b2']-=lr*delta
        progress(epoch+1,epochs)
    validate_model(model)
    if digest(model)==before:raise RuntimeError('Weights did not change')
    return model

def bench_guard():
    # Root socket applies the existing conservative controller/session guard.
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(5);client.connect('/run/orangepi-wifi-control.sock');client.sendall(b'{"action":"bench"}\n')
        raw=client.makefile('rb').readline(4097)
        if len(raw)>4096 or not raw.endswith(b'\n') or json.loads(raw).get('bench') is not True:raise RuntimeError('Bench state unavailable or flight hardware/session active')
    resource_guard()

def resource_guard():
    sensors=list(Path('/sys/class/thermal').glob('thermal_zone*/temp'))
    if not sensors:raise RuntimeError('Training paused: no temperature sensor available')
    for path in sensors:
        value=float(path.read_text())
        if not math.isfinite(value) or not 0<=value<70000:raise RuntimeError('Training paused: thermal headroom unavailable')
    fields=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    if int(fields['MemAvailable'].split()[0])<256*1024:raise RuntimeError('Training paused: memory headroom unavailable')

def training_guard():
    """Parked training can use a live DISARMED/STANDBY link, never flight control.

    This is not the root Wi-Fi/maintenance/human-activation permission gate.
    Those continue to use the stricter disconnected-controller bench guard.
    """
    if any(Path(name).exists() for name in ('/run/orangepi-flight-active','/run/orangepi-maintenance-active')):
        raise RuntimeError('Training paused: active flight or maintenance marker')
    path=Path('/run/orangepi-mavlink/status.json')
    if not path.exists():
        bench_guard();return
    value=read(path)
    if not isinstance(value,dict):raise RuntimeError('Training paused: invalid flight state')
    if value.get('connected') is False:
        bench_guard();return
    stamp=value.get('last_heartbeat_unix');updated=value.get('updated_unix');now=time.time()
    if (type(value.get('schema')) is not int or value['schema']!=1
            or value.get('authority')!='read_only_no_mavlink_transmit'
            or value.get('sensor_authority')!='advisory_receive_only_not_avoidance_qualified'
            or value.get('connected') is not True or value.get('armed') is not False
            or value.get('system_status')!='standby' or type(stamp) not in (int,float)
            or not math.isfinite(stamp) or not 0<=now-stamp<=3
            or type(updated) not in (int,float) or not math.isfinite(updated)
            or not 0<=now-updated<=3):
        raise RuntimeError('Training paused: fresh disarmed standby state not established')
    resource_guard()

def status(state,**values):
    atomic(ROOT/'status.json',{'schema':1,'updated_unix':time.time(),'state':state,'automatic_training_requested':True,'automatic_activation':False,'flight_authority':False,**values})
