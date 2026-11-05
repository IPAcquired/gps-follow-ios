"""Independent finite native Loiter sensor-loss test. TCP5810 only, no hardware."""
import argparse
import hashlib
import json
import math
import os
import pathlib
import shutil
import time
import traceback

os.environ['MAVLINK20'] = '1'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base-harness', type=pathlib.Path, required=True)
    ap.add_argument('--binary', type=pathlib.Path, required=True)
    ap.add_argument('--output-dir', type=pathlib.Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, args.output_dir/'executed_harness.py')
    shutil.copy2(args.base_harness, args.output_dir/'base_harness.py')
    binary = args.output_dir/'arducopter-snapshot'
    shutil.copy2(args.binary, binary)
    binary.chmod(0o755)
    text = args.base_harness.read_text().split('\nresults = []', 1)[0]
    ns = {'__file__': str(args.output_dir/'transport.py'), '__name__': 'transport'}
    exec(compile(text, str(args.base_harness), 'exec'), ns)
    ns.update(BINARY=binary, FILTER=5.0)
    Base, mavutil = ns['Case'], ns['mavutil']
    lines = ['PRX1_TYPE 4', 'PRX_FILT 5', 'AVOID_ENABLE 3', 'AVOID_BEHAVE 1',
             'AVOID_MARGIN 1', 'AVOID_ADAP_EN 1', 'AVOID_BACKUP_SPD 0',
             'MAV_GCS_SYSID 255', 'LOG_DISARMED 1', 'LOIT_SPEED_MS 2',
             'RC2_REVERSED 0', 'RC3_REVERSED 0', 'RC9_OPTION 40', 'RNGFND3_TYPE 0']
    for i, ori, sid, maximum in [(1,2,12,6),(2,6,16,6),(4,0,10,8)]:
        lines += [f'RNGFND{i}_TYPE 10', f'RNGFND{i}_ORIENT {ori}',
                  f'RNGFND{i}_ADDR {sid}', f'RNGFND{i}_MAV_PORT -1',
                  f'RNGFND{i}_MIN 0.2', f'RNGFND{i}_MAX {maximum}']
    (args.output_dir/'filter_5.0.parm').write_text('\n'.join(lines)+'\n')

    class DropoutCase(Base):
        def __init__(self):
            super().__init__(1, 5)
            self.rc = [1500,1500,1000,1500,65535,65535,65535,65535,2000] + [65535]*9
            self.front = True
            self.guided_velocity = None
            self.events = []
            self.publications = []
            self.phase_samples = {}
            self.result.update(test_mode='LOITER', geometry='constant distant ranges; dropout control test, no wall-clearance claim')

        def _stream(self):
            last_hb = 0
            while not self.stop.is_set():
                now = time.monotonic()
                try:
                    with self.lock:
                        if now-last_hb > 1:
                            self.m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS,
                                mavutil.mavlink.MAV_AUTOPILOT_INVALID,0,0,0)
                            last_hb = now
                        self.m.mav.rc_channels_override_send(self.m.target_system,1,*self.rc)
                        stamp = int(now*1000)&0xffffffff
                        lp = self.latest.get('LOCAL_POSITION_NED')
                        boot = int(lp[1].time_boot_ms) if lp else None
                        for sid, cm in [(12,599),(16,599)] + ([(10,799)] if self.front else []):
                            self.m.mav.distance_sensor_send(stamp,20,800,cm,
                                mavutil.mavlink.MAV_DISTANCE_SENSOR_LASER,sid,25,0)
                            self.publications.append({'monotonic_s':now,'boot_ms':boot,'id':sid,'cm':cm})
                        if self.guided_velocity is not None:
                            north, down = self.guided_velocity
                            self.m.mav.set_position_target_local_ned_send(0, self.m.target_system, 1,
                                mavutil.mavlink.MAV_FRAME_LOCAL_NED, ns['MASK_VELOCITY'],
                                0, 0, 0, north, 0, down, 0, 0, 0, 0, 0)
                        self.sensor_frames += 1
                except Exception as exc:
                    self.result['stream_error']=str(exc)
                    return
                self.stop.wait(.05)

        def pilot(self, pitch=1500, throttle=1500, avoidance=True):
            with self.lock:
                self.rc[1]=pitch; self.rc[2]=throttle; self.rc[8]=2000 if avoidance else 1000

        def phase(self, name, seconds, front, pitch=1000, throttle=1500, avoidance=True, mode=5, guided=None):
            with self.lock:
                self.front=front
                self.guided_velocity=guided
                self.pilot(pitch,throttle,avoidance)
                lp=self.latest.get('LOCAL_POSITION_NED')
                event={'name':name,'monotonic_s':time.monotonic(),
                       'boot_ms':int(lp[1].time_boot_ms) if lp else None,
                       'front':front,'pitch':pitch,'throttle':throttle,'avoidance':avoidance}
                self.events.append(event)
            print('PHASE',name,flush=True)
            self.result['phase']=name
            start=time.monotonic(); samples=[]
            while time.monotonic()-start<seconds:
                m=self.recv(.05)
                if m and m.get_type()=='LOCAL_POSITION_NED':
                    rc=self.latest.get('RC_CHANNELS')
                    samples.append({'t':time.monotonic()-start,'boot_ms':int(m.time_boot_ms),
                                    'n':m.x,'e':m.y,'d':m.z,'vn':m.vx,'ve':m.vy,'vd':m.vz,
                                    'rc2':rc[1].chan2_raw if rc else None,
                                    'rc3':rc[1].chan3_raw if rc else None,
                                    'rc9':rc[1].chan9_raw if rc else None,
                                    'mode':self.latest['HEARTBEAT'][1].custom_mode})
            self.phase_samples[name]=samples
            assert samples, f'No native position telemetry in {name}'
            assert all(x['mode']==mode for x in samples), f'Unexpected mode in {name}'
            return samples

        def fly(self):
            self.command(mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,65,50000)
            keys=['PRX1_TYPE','PRX_FILT','AVOID_ADAP_EN','AVOID_ENABLE','AVOID_MARGIN',
                  'LOIT_SPEED_MS','RC9_OPTION','ARMING_SKIPCHK']
            self.result['startup_readback']={k:self.param(k) for k in keys}
            assert self.result['startup_readback']==dict(zip(keys,[4,5,1,3,1,2,40,0]))
            deadline=time.monotonic()+70
            while time.monotonic()<deadline:
                self.recv()
                ekf=self.latest.get('EKF_STATUS_REPORT'); gps=self.latest.get('GPS_RAW_INT')
                if ekf and gps and (ekf[1].flags&0xf)==0xf and gps[1].fix_type>=3:
                    self.pump(5);break
            else: raise RuntimeError('No healthy position estimate')
            self.mode('GUIDED')
            self.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,1)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and not self.armed():self.recv()
            assert self.armed()
            self.command(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,0,0,0,0,0,0,5)
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                self.recv();gp=self.latest.get('GLOBAL_POSITION_INT')
                if gp and gp[1].relative_alt>=4500:break
            else:raise RuntimeError('Takeoff altitude not reached')
            self.velocity(0);self.pilot();self.pump(2);self.mode('LOITER');self.pump(2)
            self.phase('healthy_forward',4,True)
            self.phase('front_missing_stop',6,False)
            self.phase('front_missing_vertical',3,False,throttle=1650)
            self.phase('se_off_missing',3,False,avoidance=False)
            self.phase('se_on_missing',5,False)
            self.phase('brief_recovery',.25,True)
            self.phase('loss_after_brief_recovery',1.2,False)
            self.phase('sustained_recovery',4,True)
            self.phase('neutral',2,True,pitch=1500)
            self.mode('GUIDED')
            self.phase('guided_healthy_forward',3,True,pitch=1500,mode=4,guided=(2,0))
            self.phase('guided_front_missing_stop',5,False,pitch=1500,mode=4,guided=(2,0))
            self.phase('guided_front_missing_vertical',3,False,pitch=1500,mode=4,guided=(2,-.5))
            self.phase('guided_recovery',4,True,pitch=1500,mode=4,guided=(2,0))
            self.phase('guided_neutral',2,True,pitch=1500,mode=4,guided=(0,0))
            self.guided_velocity=None
            self.result['control_execution_pass']=True

        def close(self):
            self.pilot();self.front=True
            super().close()
            rows=[]
            for path in sorted((self.run/'logs').glob('*.BIN')):
                reader=mavutil.mavlink_connection(str(path))
                while True:
                    msg=reader.recv_match(type=['PRXL','RFND','PRX','SA','PSCN','PSCE','PSCD','RCIN'])
                    if msg is None:break
                    rows.append(msg.to_dict())
                reader.close()
            (self.run/'native_control.json').write_text(json.dumps(rows,indent=2))
            (self.run/'publications.json').write_text(json.dumps(self.publications,indent=2))
            (self.run/'phase_samples.json').write_text(json.dumps(self.phase_samples,indent=2))
            self.result['events']=self.events
            self.result['prxl']=[x for x in rows if x['mavpackettype']=='PRXL']
            checks={}
            def check(k, val):checks[k]=bool(val)
            def tail(name, seconds=1):
                p=self.phase_samples.get(name,[])
                return [x for x in p if x['t']>p[-1]['t']-seconds] if p else []
            check('normal_arming_checks',self.result.get('startup_readback',{}).get('ARMING_SKIPCHK')==0)
            check('healthy_forward_motion',any(x['vn']>1 for x in self.phase_samples.get('healthy_forward',[])))
            for phase in ['front_missing_stop','front_missing_vertical','se_on_missing','loss_after_brief_recovery']:
                p=tail(phase)
                check(phase+'_stationary_horizontal',p and max(math.hypot(x['vn'],x['ve']) for x in p)<.4)
            p=tail('front_missing_vertical')
            check('vertical_command_retained',p and min(x['vd'] for x in p)<-.2)
            for phase in ['front_missing_stop','se_on_missing']:
                p=[x for x in self.phase_samples.get(phase,[]) if x['t']>.8]
                check(phase+'_no_large_recoil',p and min(x['vn'] for x in p)>-.35)
            check('guided_healthy_forward_motion',any(x['vn']>1 for x in self.phase_samples.get('guided_healthy_forward',[])))
            for phase in ['guided_front_missing_stop','guided_front_missing_vertical']:
                p=tail(phase)
                check(phase+'_stationary_horizontal',p and max(math.hypot(x['vn'],x['ve']) for x in p)<.4)
            p=[x for x in self.phase_samples.get('guided_front_missing_stop',[]) if x['t']>.8]
            check('guided_stop_no_large_recoil',p and min(x['vn'] for x in p)>-.35)
            p=tail('guided_front_missing_vertical')
            check('guided_vertical_command_retained',p and min(x['vd'] for x in p)<-.2)
            check('guided_recovery_restores_authority',any(x['vn']>1 for x in tail('guided_recovery')))
            check('se_off_restores_authority',any(x['vn']>1 and x['rc9']==1000 for x in self.phase_samples.get('se_off_missing',[])))
            check('healthy_recovery_restores_authority',any(x['vn']>1 for x in tail('sustained_recovery')))
            events={x['name']:x for x in self.events}
            if 'front_missing_stop' in events and 'sustained_recovery' in events:
                lost=events['front_missing_stop']['boot_ms']*1000
                recovery=events['sustained_recovery']['boot_ms']*1000
                masks=[x for x in self.result['prxl'] if lost<=x['TimeUS']<=recovery+4000000]
                check('front_only_missing_mask',any(x['Mask']==1 for x in masks) and all(x['Mask'] in [0,1] for x in masks))
                losses=[x for x in masks if x['Mask']==1]
                check('drop_detected_within_0p8s',losses and 0<=losses[0]['TimeUS']-lost<=800000)
                clears=[x for x in masks if x['Mask']==0]
                check('no_clear_on_brief_recovery',not any(x['TimeUS']<recovery for x in clears))
                check('clear_after_1s_healthy',clears and 950000<=clears[0]['TimeUS']-recovery<=1400000)
                stopped_front=[x for x in rows if x['mavpackettype']=='RFND' and x['Instance']==3 and lost+800000<x['TimeUS']<lost+5000000]
                check('front_backend_reports_nodata',stopped_front and all(x['Stat']==1 for x in stopped_front))
                for inst in [0,1]:
                    side=[x for x in rows if x['mavpackettype']=='RFND' and x['Instance']==inst and lost+800000<x['TimeUS']<lost+5000000]
                    check(f'healthy_side_instance_{inst}',side and all(x['Stat']==4 for x in side))
            else:check('complete_phase_sequence',False)
            check('landed_disarmed',self.result.get('landed_disarmed'))
            check('owned_process_stopped',self.result.get('owned_process_stopped'))
            check('pinned_binary_unchanged',self.result.get('pinned_binary_unchanged'))
            self.result['checks']=checks
            self.result['pass']=all(checks.values()) and self.result.get('control_execution_pass',False) and not self.result.get('stream_error')

    case=DropoutCase()
    try:case.start();case.fly()
    except Exception as exc:
        case.result.update(error=str(exc),traceback=traceback.format_exc())
    finally:case.close()
    case.result['limitations']=['Native simulator with constant distant returns; no hardware/motor test.',
        'RC9 models the SE avoidance function; no real transmitter mapping is changed.',
        'Motion assertions are simulator behavior, not loaded physical stopping certification.',
        'PRXL/NoData and sustained side updates test bridge loss/recovery; packet-age unit regression is separate.']
    (case.run/'result.json').write_text(json.dumps(case.result,indent=2)+'\n')
    summary={k:v for k,v in case.result.items() if k not in ['samples','adpm','traceback']}
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    return 0 if case.result.get('pass') else 1


if __name__=='__main__':raise SystemExit(main())
