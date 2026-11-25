"""Apply narrow, repeatable edits to the captured release; preserve unrelated files."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
def original(name):return (ROOT/'original'/name).read_text(encoding='utf8')
def store(name,text):(ROOT/name).write_text(text,encoding='utf8',newline='\n')
def swap(text,old,new,n=1):
    if text.count(old)!=n:raise ValueError(old[:90])
    return text.replace(old,new)

display=original('display_telemetry.py')
display=swap(display,'import math','from controller_profile import controller_profile\nimport math')
display=swap(display,'    h743 = {}\n','    h743 = {}  # Existing schema-1 wire key.\n    profile = controller_profile(flight, now)\n')
display=swap(display,"    heartbeat_fresh = (flight.get('connected')","    heartbeat_fresh = (profile['source_state'] == 'matching' and flight.get('connected')")
display=swap(display,"and type(identity.get('component_id')) is int\n                   and record.get('source_system_id')","and type(identity.get('component_id')) is int\n                   and controller_profile(flight, now)['source_state'] == 'matching'\n                   and type(record.get('source_system_id')) is int and type(record.get('source_component_id')) is int\n                   and record.get('source_system_id')")
display=swap(display,"'h743': h743, 'pi': bounded_pi(pi)","'controller_profile': profile, 'h743': h743, 'pi': bounded_pi(pi)")
display=swap(display,"faults.append({'component': 'h743', 'severity': 'warning', 'code': 'H743_TELEMETRY_UNAVAILABLE',\n                       'text': 'Pi API is responding; H743 heartbeat is unavailable or stale.', 'age_ms': heartbeat_age})","""message = ('Telemetry source differs from the configured MAVLink source.' if profile['source_state'] == 'mismatch'
                   else 'Heartbeat source is unverified.' if profile['presence'] == 'heartbeat'
                   else 'No recent controller heartbeat. Physical presence is unknown.')
        faults.append({'component': 'flight_controller', 'severity': 'warning', 'code': 'CONTROLLER_TELEMETRY_UNVERIFIED',
                       'text': message, 'age_ms': heartbeat_age})""")
display=swap(display,"    messages = recent_messages(flight, now)","    messages = recent_messages(flight, now) if heartbeat_fresh else []")
display=swap(display,"                           and battery.get('source_system_id')", "                           and type(battery.get('source_system_id')) is int and type(battery.get('source_component_id')) is int\n                           and battery.get('source_system_id')")
display=swap(display,"                       and ground.get('source_system_id')", "                       and type(ground.get('source_system_id')) is int and type(ground.get('source_component_id')) is int\n                       and ground.get('source_system_id')")
display=swap(display,"    services = bounded_services(services)","""    health = bounded_health(health)
    if not heartbeat_fresh and 'flight_controller' in health:
        health['flight_controller'].update(status='no_data', fresh=False, reason='no_matching_fresh_heartbeat')
    services = bounded_services(services)""")
display=swap(display,"'sensor_health': bounded_health(health)","'sensor_health': health")
store('display_telemetry.py',display)

app=original('orangepi-companion')
app=swap(app,'from display_telemetry import','from controller_profile import MODEL, SENSOR_LINKS, board_reference, controller_profile, source_pair\nfrom display_telemetry import')
app=swap(app,"    if state.get('connected') is False and state.get('last_heartbeat_unix') is None:return True\n","    if type(state.get('schema')) is not int or state['schema'] != 1 or controller_profile(state, now)['source_state'] != 'matching':return False\n")
app=swap(app,"            flight=live_flight_status()\n            if action not in {'probe','release_all'} and flight.get('connected') is True and flight.get('armed') is not False:","            if action not in {'probe','release_all'} and not browser_owner_safe():")
app=swap(app,"    if not valid_monitor or not valid_updated or age_ms > 7000:","    identity = controller_profile(value if valid_monitor else {}, now)\n    if not valid_monitor or not valid_updated or age_ms > 7000 or identity['source_state'] != 'matching':")
app=swap(app,'"schema": 1, "connected": False, "reason": "no_fresh_heartbeat",','''"schema": 1, "connected": False, "reason": "unverified_controller_source" if identity["presence"] == "heartbeat" else "no_fresh_heartbeat",
            "controller_profile": identity, "heartbeat_observed": identity["presence"] == "heartbeat",
            "last_heartbeat_unix": value.get("last_heartbeat_unix") if identity["presence"] == "heartbeat" else None,
            "h743_source": value.get("h743_source") if valid_monitor else None, "expected_source": value.get("expected_source") if valid_monitor else None,''')
app=swap(app,'    result = dict(value)\n    result.update({"data_age_ms"','    result = dict(value)\n    result["controller_profile"] = identity\n    result.update({"data_age_ms"')
app=swap(app,'"transport": "none", "connection_id": None, "flight_session_id": None,','"transport": value.get("transport") if identity["presence"] == "heartbeat" else "none", "connection_id": None, "flight_session_id": None,')
app=swap(app,"    valid_fix = (gps_record.get('message_type')",'''    def same_source(record):
        pair = {"system_id":record.get("source_system_id"), "component_id":record.get("source_component_id")}
        return source_pair(pair) == source_pair(value.get("expected_source"))
    valid_fix = (same_source(gps_record) and gps_record.get('message_type')''')
app=swap(app,"        if not isinstance(record, dict): return {}\n        stamp_value","        if not isinstance(record, dict) or not same_source(record): return {}\n        stamp_value")
app=swap(app,"    metadata = read_json(ARDUPILOT_REFERENCE / 'reference.json', {})","""    words = prompt.lower()
    if any(term in words for term in ('corvon', 'h743', 'hwdef', 'board definition')):
        return board_reference()
    metadata = read_json(ARDUPILOT_REFERENCE / 'reference.json', {})""")
app=swap(app,"'live_h743_version_match_verified','observed_h743_identity','live_base_commit_prefix_match','live_firmware_bytes_attested',","")
app=swap(app,"    if not metadata: return {'status':'not_installed'}\n    words = prompt.lower()","    result.update(configured_board=MODEL, evidence_scope='historical_source_reference', live_firmware_bytes_attested=False)\n    if not metadata: return {'status':'not_installed', 'configured_board':MODEL}")
app=swap(app,",('h743','libraries/AP_HAL_ChibiOS/hwdef/MicoAir743v2/hwdef.dat')","")
app=swap(app,"'flight_controller': device_exists('/dev/h743', '/dev/rfcomm0')","'flight_controller': device_exists('/dev/ttyS0', '/dev/h743')")
app=swap(app,"device_exists('/dev/rplidar', '/dev/rplidar-c1-usb')","device_exists('/dev/ttyS2', '/dev/rplidar')")
app=swap(app,"device_exists('/dev/matrix-lidar', '/dev/dfrobot-matrix-lidar',\n                                      '/dev/dfrobot-matrix-uart7')","device_exists('/dev/ttyS7', '/dev/dfrobot-matrix-uart7')")
app=swap(app,'        "device_nodes": device_nodes,','        "device_nodes": device_nodes,\n        "configured_sensor_links": SENSOR_LINKS,')
app=app.replace('MicoAir H743','CORVON743V2').replace('H743 parameter','CORVON743V2 parameter').replace('"H743"','"CORVON743V2"').replace('H743 heartbeat','CORVON743V2 heartbeat').replace('H743 telemetry','CORVON743V2 telemetry').replace('H743 battery','CORVON743V2 battery').replace('H743 controls flight','CORVON743V2 controls flight').replace('H743 settings unchanged','controller settings preserved').replace('fresh_h743_heartbeat','fresh_matching_controller_heartbeat')
app=app.replace('"h743", "motor"', '"corvon", "h743", "motor"').replace('("h743", "flight",', '("corvon", "h743", "flight",').replace('("flight controller", "h743")','("flight controller", "corvon", "h743")').replace('"h743 status", "flight status"', '"corvon status", "h743 status", "flight status"')
app=swap(app,'Connect the CORVON743V2 to see live, fresh-flight data.','Check the controller power and the UART0 to UART4 link.')
store('orangepi-companion',app)
for name in ('orangepi-ai-team','qwen_adapter_worker.py'):
    text=original(name).replace('MicoAir H743 V2','CORVON743V2')
    store(name,text)

for name in ('companion-app.js','companion-app.html','field.js','field.html','phone.html','orangepi-ai-team-gui',
             'orangepi-jev-advisor','orangepi-offline-code-review','environment_awareness.py'):
    text=re.sub(r'MicoAir H743(?: V2)?|\bH743\b','CORVON743V2',original(name))
    if name=='field.js':
        text=swap(text,"flight?'Connected':'No fresh heartbeat'","flight?'Matching heartbeat':snapshot?.controller_profile?.presence==='heartbeat'?'Unverified source':'No recent heartbeat'")
    if name=='companion-app.js':
        text=text.replace("['H7','CORVON743V2 controller','Flight authority']","['FC','CORVON743V2','Flight authority']")
    if name=='environment_awareness.py':
        text=swap(text,"    source = flight.get('h743_source')","    from controller_profile import controller_profile\n    source = flight.get('h743_source')")
        text=swap(text,"and flight.get('authority') == FLIGHT_AUTHORITY","and controller_profile(flight, now)['source_state'] == 'matching'\n        and flight.get('authority') == FLIGHT_AUTHORITY")
    store(name,text)
text=original('orangepi-ai-improvement').replace('"required_all": ("h743",)','"required_all": ("corvon743v2",)').replace('"ignore the h743",','"ignore the corvon", "ignore the h743",')
store('orangepi-ai-improvement',text)
store('browser_desktop.py',original('browser_desktop.py').replace('Fresh disarmed or confirmed absent H743 status required','Fresh matching disarmed controller status required'))
text=original('orangepi-bin-analyzer')
text=swap(text,'Fail closed on a present-but-invalid flight status, but not an absent H743.','Decide whether archived log processing must wait; a missing monitor has no controller presence evidence.')
text=swap(text,'        if status.get("armed") is True:', '''        from controller_profile import controller_profile
        if status["connected"] and controller_profile(status, now)["source_state"] != "matching":
            return True, "controller_source_unverified"
        if status.get("armed") is True:''')
text=text.replace('"h743_armed"','"controller_armed"').replace('"h743_disarmed_or_disconnected"','"controller_disarmed" if status["connected"] else "no_connected_monitor_workload"')
store('orangepi-bin-analyzer',text)
