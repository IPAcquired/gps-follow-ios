#!/usr/bin/env python3
"""Finite native Loiter obstacle test; isolated instance 4 / TCP5800 only.

Reuses the reviewed fixed-wall test transport/lifecycle methods without running
its top-level flights. Simulator starts with its own copied binary, EEPROM,
parameter defaults, logs and working directory. No hardware paths are used.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-harness', required=True, type=pathlib.Path)
    parser.add_argument('--binary', required=True, type=pathlib.Path)
    parser.add_argument('--output-dir', required=True, type=pathlib.Path)
    parser.add_argument('--filter', required=True, type=float)
    parser.add_argument('--rangefinder-backend', action='store_true',
                        help='Use actual PRX1_TYPE4 RangeFinder bridge with right/left/front instance ordering.')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(pathlib.Path(__file__), args.output_dir/'executed_harness.py')
    shutil.copy2(args.base_harness, args.output_dir/'base_harness.py')
    pinned = args.output_dir/'arducopter-snapshot'
    shutil.copy2(args.binary, pinned)
    pinned.chmod(0o755)
    base = args.base_harness.read_text()
    prefix = base.split('\nresults = []', 1)[0]
    old = '1500, 1500, 1000, 1500, 65535, 65535, 65535, 65535)'
    assert prefix.count(old) == 1, 'Reviewed RC transport signature changed'
    prefix = prefix.replace(old, '*self.rc)')
    if args.rangefinder_backend:
        # All packets intentionally claim downward orientation; nonzero IDs select
        # distinct rangefinder instances whose configured orientations win.
        prefix = prefix.replace('min(1999, max(20, distance * 100))',
                                'min(799, max(20, distance * 100))')
        prefix = prefix.replace('[(10, 0, front_cm), (12, 2, 1999), (16, 6, 1999)]',
                                '[(10, 25, front_cm), (12, 25, 599), (16, 25, 599)]')
    ns = {'__file__': str(args.output_dir/'transport.py'), '__name__': 'isolated_transport'}
    exec(compile(prefix, str(args.base_harness), 'exec'), ns)
    ns['FILTER'] = args.filter
    ns['BINARY'] = pinned
    BaseCase, mavutil = ns['Case'], ns['mavutil']
    defaults = args.output_dir/f'filter_{args.filter}.parm'
    param_lines = [
        '# SIMULATION ONLY. Fresh EEPROM; no real controller is accessed.',
        'PRX1_TYPE 4' if args.rangefinder_backend else 'PRX1_TYPE 2',
        f'PRX_FILT {args.filter}', 'AVOID_ENABLE 3',
        'AVOID_BEHAVE 1', 'AVOID_MARGIN 1', 'AVOID_ADAP_EN 1',
        'MAV_GCS_SYSID 255', 'LOG_DISARMED 1',
        '# Full forward pilot input with an explicit low Loiter speed cap.',
        'LOIT_SPEED_MS 2', 'RC2_REVERSED 0', 'RC3_REVERSED 0',
    ]
    if args.rangefinder_backend:
        param_lines += ['RNGFND3_TYPE 0']
        for instance, orientation, sid, maximum in [(1,2,12,6),(2,6,16,6),(4,0,10,8)]:
            param_lines += [f'RNGFND{instance}_TYPE 10', f'RNGFND{instance}_ORIENT {orientation}',
                            f'RNGFND{instance}_ADDR {sid}', f'RNGFND{instance}_MAV_PORT -1',
                            f'RNGFND{instance}_MIN 0.2', f'RNGFND{instance}_MAX {maximum}']
    defaults.write_text('\n'.join(param_lines)+'\n')

    class LoiterCase(BaseCase):
        def __init__(self):
            self.rc = (1500,1500,1000,1500,65535,65535,65535,65535)
            super().__init__(1,4)
            self.result.update(test_mode='LOITER', pilot_forward_pwm=1000,
                               loiter_speed_cap_mps=2.0,
                               rangefinder_backend=args.rangefinder_backend,
                               base_harness_sha256=hashlib.sha256(base.encode()).hexdigest(),
                               harness_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
            self.result['boundary_source_sha256']=hashlib.sha256(
                pathlib.Path('/home/daddy_nate/ardupilot-adaptive-clean/libraries/AP_Proximity/AP_Proximity_Boundary_3D.cpp').read_bytes()).hexdigest()
            self.result['rangefinder_source_sha256']=hashlib.sha256(
                pathlib.Path('/home/daddy_nate/ardupilot-adaptive-clean/libraries/AP_RangeFinder/AP_RangeFinder_MAVLink.cpp').read_bytes()).hexdigest()

        def pilot(self, pitch=1500, throttle=1500):
            with self.lock:
                self.rc=(1500,pitch,throttle,1500,65535,65535,65535,65535)

        def sample(self, msg, start, phase):
            if msg is None or msg.get_type()!='LOCAL_POSITION_NED':
                return None
            att=self.latest.get('ATTITUDE')
            rc=self.latest.get('RC_CHANNELS')
            return {'phase':phase, 't':time.monotonic()-start,
                    'n':float(msg.x), 'e':float(msg.y),'d':float(msg.z),
                    'vn':float(msg.vx),'ve':float(msg.vy),
                    'gap':self.wall_n-float(msg.x),
                    'yaw':float(att[1].yaw) if att else None,
                    'pitch':float(att[1].pitch) if att else None,
                    'rc2':int(rc[1].chan2_raw) if rc else None,
                    'mode':int(self.latest['HEARTBEAT'][1].custom_mode)}

        def fly(self):
            self.command(mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,65,50000)
            keys=['AVOID_ADAP_EN','AVOID_ENABLE','AVOID_BEHAVE','AVOID_MARGIN',
                  'AVOID_ADAP_RT','AVOID_ADAP_MAX','PRX1_TYPE','PRX_FILT',
                  'ARMING_SKIPCHK','LOIT_SPEED_MS','RC2_REVERSED','RC3_REVERSED']
            rb={k:self.param(k) for k in keys}
            if args.rangefinder_backend:
                for instance, orientation, sid in [(1,2,12),(2,6,16),(4,0,10)]:
                    for suffix, expected in [('TYPE',10),('ORIENT',orientation),('ADDR',sid),('MAV_PORT',-1)]:
                        key=f'RNGFND{instance}_{suffix}'
                        rb[key]=self.param(key)
                        assert rb[key]==expected, f'Rangefinder mapping mismatch: {key}'
            self.result['startup_readback']=rb
            assert rb['ARMING_SKIPCHK']==0, 'No arming checks may be skipped'
            assert rb['AVOID_ADAP_EN']==1 and rb['AVOID_BEHAVE']==1
            assert rb['AVOID_MARGIN']==1 and rb['PRX1_TYPE']==(4 if args.rangefinder_backend else 2)
            assert abs(rb['AVOID_ADAP_RT']-.35)<1e-5 and rb['AVOID_ADAP_MAX']==1
            assert abs(rb['PRX_FILT']-args.filter)<1e-6
            assert rb['LOIT_SPEED_MS']==2 and rb['RC2_REVERSED']==0
            deadline=time.monotonic()+70
            while time.monotonic()<deadline:
                self.recv()
                ekf=self.latest.get('EKF_STATUS_REPORT')
                lp=self.latest.get('LOCAL_POSITION_NED')
                gps=self.latest.get('GPS_RAW_INT')
                if ekf and lp and gps and (ekf[1].flags&0x0f)==0x0f and gps[1].fix_type>=3:
                    self.pump(5)
                    break
            else:
                raise RuntimeError(f'Healthy position not ready: {self.status[-10:]}')
            self.mode('GUIDED')
            self.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,1)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and not self.armed():
                self.recv()
            assert self.armed()
            self.command(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,0,0,0,0,0,0,5)
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                self.recv()
                gp=self.latest.get('GLOBAL_POSITION_INT')
                if gp and gp[1].relative_alt>=4500:
                    break
            else:
                raise RuntimeError('Normal Guided takeoff did not reach 4.5m')
            self.result['takeoff_altitude_m']=gp[1].relative_alt/1000
            self.velocity(0)
            self.pilot()
            self.pump(2)
            self.mode('LOITER')
            self.pump(2)
            assert self.latest['HEARTBEAT'][1].custom_mode==5
            self.wall_n=float(self.latest['LOCAL_POSITION_NED'][1].x)+6.0
            self.result['wall_n_m']=self.wall_n
            self.result['phase']='loiter_held_forward'
            self.pilot(1000)
            start=time.monotonic()
            while time.monotonic()-start<15:
                s=self.sample(self.recv(.05),start,'loiter_held_forward')
                if s:
                    self.samples.append(s)
            assert len(self.samples)>100, 'Insufficient fresh position samples'
            assert all(s['mode']==5 for s in self.samples), 'Mode left Loiter'
            assert max(s['vn'] for s in self.samples)>1.5, 'Approach did not reach meaningful 1.5m/s'
            assert any(s['rc2']==1000 for s in self.samples), 'RC pitch command never received'
            assert max(abs(s['yaw']) for s in self.samples if s['yaw'] is not None)<.35
            self.result.update(sample_count=len(self.samples),
                min_gap_m=min(s['gap'] for s in self.samples),
                max_vn_mps=max(s['vn'] for s in self.samples),
                final_gap_m=self.samples[-1]['gap'], final_vn_mps=self.samples[-1]['vn'])
            self.pilot()
            neutral=[]
            start=time.monotonic()
            while time.monotonic()-start<2:
                s=self.sample(self.recv(.05),start,'neutral')
                if s: neutral.append(s)
            self.result['neutral_samples']=neutral
            self.result['min_gap_including_neutral_m']=min([s['gap'] for s in self.samples+neutral])
            self.result['phase']='loiter_retreat'
            self.pilot(2000)
            retreat=[]
            start=time.monotonic()
            while time.monotonic()-start<3:
                s=self.sample(self.recv(.05),start,'loiter_retreat')
                if s: retreat.append(s)
            self.result['retreat_samples']=retreat
            self.result['retreat_min_vn_mps']=min(s['vn'] for s in retreat) if retreat else None
            assert retreat and min(s['vn'] for s in retreat)<-.3
            self.pilot()
            self.result['control_execution_pass']=True
            self.result['virtual_wall_penetrated']=self.result['min_gap_including_neutral_m']<0
            self.result['one_meter_clearance_pass_with_0p1m_tolerance']=self.result['min_gap_including_neutral_m']>=.9

        def close(self):
            self.pilot()
            super().close()
            if args.rangefinder_backend:
                rfnd=[]
                for log in sorted((self.run/'logs').glob('*.BIN')):
                    reader=mavutil.mavlink_connection(str(log))
                    while True:
                        msg=reader.recv_match(type='RFND')
                        if msg is None: break
                        rfnd.append(msg.to_dict())
                    reader.close()
                self.result['rangefinder_logged_instances']=sorted({x['Instance'] for x in rfnd})
                self.result['rangefinder_log_count']=len(rfnd)
                self.result['rangefinder_log_head']=rfnd[:12]
                self.result['rangefinder_logged_directions']={str(i):sorted({x['Orient'] for x in rfnd if x['Instance']==i and x['Stat']==4}) for i in [0,1,3]}
                self.result['rangefinder_bridge_proven']=self.result['rangefinder_logged_directions']=={'0':[2],'1':[6],'3':[0]}
                self.result['pass'] &= self.result['rangefinder_bridge_proven']

    case=LoiterCase()
    try:
        case.start()
        case.fly()
    except Exception as exc:
        case.result.update(error=str(exc),traceback=traceback.format_exc())
        case.result['pass']=False
    finally:
        case.close()
    case.result['limitations']=[
        'Simulation only; synthetic front range with position/yaw latency and quantization.',
        'Low 2m/s Loiter speed cap is an explicit simulator-only setting.',
        'Guided used only for takeoff; obstacle approach, held stick and retreat are Loiter.',
        'No downward sensor, body-tilt range correction, rear coverage or real aircraft tune modeled.',
        'The 0.90m criterion is a test tolerance; it does not guarantee one-meter physical stopping.',
    ]
    (case.run/'result.json').write_text(json.dumps(case.result,indent=2)+'\n')
    summary={k:v for k,v in case.result.items() if k not in ['samples','neutral_samples','retreat_samples','adpm','traceback']}
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    return 0 if case.result.get('pass') else 1


if __name__=='__main__':
    raise SystemExit(main())
