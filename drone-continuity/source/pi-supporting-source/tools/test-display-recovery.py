import concurrent.futures,datetime,json,pathlib,subprocess
root=pathlib.Path(__file__).resolve().parent.parent
project=root/'work/display-recovery-candidate'
linux='/mnt/c/'+str(project)[3:].replace('\\','/')
def run(name):
    binary='/tmp/display-candidate-20261023-'+name
    json_include='/mnt/c/Users/Daddy Nate/Documents/Codex/2026-10-23/esp32-orange-pi-drone-connection/work/display-candidate/.pio/libdeps/flight_team/ArduinoJson/src'
    cmd=['wsl.exe','-d','Ubuntu','--','g++','-std=c++11','-Wall','-Wextra','-Werror','-I',linux+'/include','-I',json_include,linux+'/test/'+name+'.cpp','-o',binary]
    if name=='pinned_connection':cmd.extend(['-I',linux+'/test/stubs'])
    build=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    if build.returncode:return {'test':name,'passed':False,'build':build.stderr}
    args=[binary]
    if name=='display_telemetry':args.append('/mnt/c/Users/Daddy Nate/Documents/Codex/2026-10-23/esp32-orange-pi-drone-connection/work/current-audit/fixtures/display-worst-case.json')
    result=subprocess.run(['wsl.exe','-d','Ubuntu','--',*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    return {'test':name,'passed':result.returncode==0,'output':result.stdout.strip(),'stderr':result.stderr}
if __name__=='__main__':
    names=['power','gesture','keyboard','touch','wireless','maintenance','truth','storage_format','orientation','time_bootstrap','drone_position','phone_location','session_policy','display_telemetry','telemetry_layout','fault_cases','link_fault_policy','browser_phone','wifi_recovery','tls_memory_recovery','widget_cache','quick_connect','light_pattern','ai_ui_state','status_bar','appearance_palette','owner_lease','desktop_geometry']
    names.extend(['desktop_codec','display_battery','desktop_controls','pinned_connection','buffered_json','integrity_matrix'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,names))
    report={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':results,'all_pass':all(item['passed'] for item in results),'hardware_actions':0}
    (root/'outputs').mkdir(exist_ok=True)
    (root/'outputs/display-recovery-tests.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2));raise SystemExit(0 if report['all_pass'] else 1)
