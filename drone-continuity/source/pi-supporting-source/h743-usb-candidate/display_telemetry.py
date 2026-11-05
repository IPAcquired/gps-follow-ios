"""Compact read-only display measurements; each source keeps its own expiry."""
import math
import os
from pathlib import Path
import re
import threading
import time
import subprocess
import json
from datetime import datetime, timezone

_cpu_lock = threading.Lock()
_cpu_previous = None
_fault_lock = threading.Lock()
_fault_state = {'busy': False, 'sampled_unix': None, 'units': [], 'sample_succeeded': False}


def sample_failed_services():
    units, success = [], True
    for user in (False, True):
        command = ['/usr/bin/systemctl'] + (['--user'] if user else []) + ['--failed', '--plain', '--no-legend', '--no-pager']
        try:
            result = subprocess.run(command, capture_output=True, timeout=2, check=False)
            if result.returncode:
                success = False
                continue
            for line in result.stdout.decode('utf-8', 'replace')[:16384].splitlines():
                columns = line.lstrip(' \u25cf').split()
                if not columns: continue
                unit = columns[0]
                if re.fullmatch(r'[A-Za-z0-9@_.:-]{1,100}', unit) and unit.startswith(('orangepi-', 'mavlink-', 'hostapd', 'ssh', 'bluetooth', 'systemd-timesyncd', 'llama')):
                    units.append(('user:' if user else 'system:') + unit)
        except (OSError, subprocess.TimeoutExpired):
            success = False
    return sorted(set(units))[:8], success


def service_faults(now):
    def refresh():
        try:
            units, success = sample_failed_services()
            with _fault_lock:
                _fault_state.update(sampled_unix=time.time(), units=units, sample_succeeded=success)
        finally:
            with _fault_lock: _fault_state['busy'] = False
    with _fault_lock:
        stamp = _fault_state['sampled_unix']
        if (stamp is None or now - stamp >= 10) and not _fault_state['busy']:
            _fault_state['busy'] = True
            threading.Thread(target=refresh, name='display-service-faults', daemon=True).start()
        result = dict(_fault_state)
    result.pop('busy', None)
    age = clock_age(result['sampled_unix'], now)
    result.update(age_ms=age, fresh=age is not None and age <= 15000,
                  source='bounded_systemctl_failed_units_not_full_system_health')
    return result


def recent_messages(flight, now):
    result = []
    messages = flight.get('messages', [])
    if not isinstance(messages, list): return result
    for message in messages[-6:]:
        if not isinstance(message, dict): continue
        text, stamp = message.get('text'), message.get('time_utc')
        if not isinstance(text, str) or not isinstance(stamp, str): continue
        try:
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if parsed.tzinfo is None: continue
            epoch = parsed.timestamp()
        except (ValueError, OverflowError): continue
        age = clock_age(epoch, now)
        if age is not None and age <= 10000:
            result.append({'text': display_text(text, 64), 'severity': display_text(message.get('severity', 'unknown'), 16),
                           'time_utc': stamp[:40], 'age_ms': age, 'fresh': True, 'source': 'STATUSTEXT'})
    return result


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def display_text(value, maximum):
    if not isinstance(value, str): return ''
    return ''.join(character if 32 <= ord(character) <= 126 else '?' for character in value[:maximum])


def bounded_health(value):
    result = {}
    value = value if isinstance(value, dict) else {}
    for name in ('camera', 'rplidar', 'matrix_lidar', 'flight_controller'):
        row = value.get(name, {})
        if not isinstance(row, dict): row = {}
        age = row.get('data_age_ms')
        age = age if type(age) is int and 0 <= age <= 86400000 else None
        fresh = row.get('fresh') is True and row.get('status') == 'fresh_data' and age is not None and age <= 3000
        result[name] = {'status': 'fresh_data' if fresh else 'no_data', 'fresh': fresh,
                        'device_node_present': row.get('device_node_present') is True,
                        'data_age_ms': age, 'reason': display_text(row.get('reason'), 80) or 'unavailable'}
    return result


def bounded_phone(value):
    value = value if isinstance(value, dict) else {}
    status = value.get('status')
    if not isinstance(status, str) or status not in {'fresh', 'stale', 'stopped', 'unavailable'}: status = 'unavailable'
    result = {'source': 'phone_gps', 'position_is_drone_gps': False, 'status': status, 'ttl_ms': 3000,
              'authority': 'advisory_only', 'transport_delay_verified': False,
              'transport': 'phone_browser_wifi' if value.get('provenance') == 'authenticated_phone_browser' else 'display_ble'}
    age, accuracy, lat, lon = (value.get(key) for key in ('age_ms', 'accuracy_m', 'lat', 'lon'))
    fresh = (status == 'fresh' and type(age) is int and 0 <= age < 3000 and number(accuracy) and 0 < accuracy <= 30
             and number(lat) and -90 <= lat <= 90 and number(lon) and -180 <= lon <= 180)
    if fresh: result.update(age_ms=age, accuracy_m=accuracy, lat=lat, lon=lon)
    elif status == 'fresh': result['status'] = 'unavailable'
    return result


def bounded_services(value):
    value = value if isinstance(value, dict) else {}
    units = value.get('units', [])
    units = [display_text(unit, 64) for unit in units[:8] if isinstance(unit, str)] if isinstance(units, list) else []
    age = value.get('age_ms')
    age = age if type(age) is int and 0 <= age <= 86400000 else None
    return {'units': units, 'age_ms': age, 'sample_succeeded': value.get('sample_succeeded') is True,
            'fresh': value.get('fresh') is True and age is not None and age <= 15000,
            'source': 'bounded_failed_service_inventory'}


def bounded_camera(vision, now):
    vision = vision if isinstance(vision, dict) else {}
    age = clock_age(vision.get('captured_unix'), now)
    fresh = (vision.get('schema') == 1 and vision.get('authority') == 'observation_only_no_flight_commands'
             and vision.get('status') == 'active' and vision.get('fresh') is True
             and age is not None and age <= 2000)
    detections = []
    rows = vision.get('detections', [])
    if fresh and isinstance(rows, list):
        for row in rows[:100]:
            if not isinstance(row, dict): continue
            box, confidence, identifier = row.get('box'), row.get('confidence'), row.get('class_id')
            if (not isinstance(box, list) or len(box) != 4 or any(not number(value) or not 0 <= value <= 65535 for value in box)
                    or box[2] <= box[0] or box[3] <= box[1] or not number(confidence) or not 0 <= confidence <= 1
                    or type(identifier) is not int or not 0 <= identifier <= 9999): continue
            detections.append({'class_id': identifier, 'label': display_text(row.get('label'), 24),
                               'confidence': confidence})
    return {'fresh': fresh, 'age_ms': age, 'detection_count': len(detections) if fresh else None,
            'detections': detections[:4], 'detections_truncated': len(detections) > 4,
            'source': 'validated_vision_status', 'qualification': 'observation_not_clearance'}


def bounded_pi(fields):
    result = {}
    names = ('load_1m', 'load_5m', 'load_15m', 'cpu_busy_percent', 'cpu_max_temperature_c',
             'memory_total_bytes', 'memory_available_bytes', 'uptime_seconds', 'wifi_rssi_dbm',
             'wifi_ssid', 'ai_process_active', 'ai_state', 'api_alive',
             'board_current_a', 'usb_port_current_a', 'input_voltage_v')
    for name in names:
        row = fields.get(name, {})
        if not isinstance(row, dict): row = {}
        value, age = row.get('value'), row.get('age_ms')
        valid = type(value) is bool or number(value) or isinstance(value, str)
        age = age if type(age) is int and 0 <= age <= 86400000 else None
        fresh = row.get('fresh') is True and valid and age is not None and age <= 5000
        if isinstance(value, str): value = display_text(value, 48)
        result[name] = metric(value, display_text(row.get('unit'), 24), display_text(row.get('source'), 72),
                              age, fresh, display_text(row.get('reason'), 48) or 'unavailable')
    return result


def metric(value=None, unit='', source='', age_ms=None, fresh=False, reason='unavailable'):
    return {'value': value if fresh else None, 'unit': unit, 'fresh': bool(fresh),
            'age_ms': age_ms, 'source': source, 'reason': 'fresh' if fresh else reason}


def clock_age(stamp, now):
    return max(0, int((now - stamp) * 1000)) if number(stamp) and 0 < stamp <= now else None


def record_field(flight, kind, name, unit, now, ttl, instance=0):
    records = flight.get('sensors', {})
    record = records.get(f'{kind}:{instance}', {}) if isinstance(records, dict) else {}
    if not isinstance(record, dict): record = {}
    source = f'{kind}:{instance}.{name}'
    values, clocks, flags = (record.get(key, {}) for key in ('values', 'field_updated_unix', 'field_fresh'))
    if not all(isinstance(value, dict) for value in (values, clocks, flags)):
        return metric(unit=unit, source=source)
    value, age = values.get(name), clock_age(clocks.get(name), now)
    identity = flight.get('h743_source', {})
    identity_ok = (isinstance(identity, dict) and type(identity.get('system_id')) is int
                   and type(identity.get('component_id')) is int
                   and record.get('source_system_id') == identity['system_id']
                   and record.get('source_component_id') == identity['component_id'])
    heartbeat_age = clock_age(flight.get('last_heartbeat_unix'), now)
    fresh = (flight.get('connected') is True and flight.get('fresh') is True and identity_ok
             and heartbeat_age is not None and heartbeat_age <= 2000
             and record.get('message_type') == kind and type(record.get('instance')) is int
             and record['instance'] == instance and flags.get(name) is True
             and age is not None and age <= ttl and number(value))
    return metric(value, unit, source, age, fresh, 'stale_or_unknown_field')


def text_file(path):
    try: return Path(path).read_text(encoding='utf-8').strip()
    except OSError: return ''


def sample_pi():
    global _cpu_previous
    fields = {}
    try:
        for key, value in zip(('load_1m', 'load_5m', 'load_15m'), os.getloadavg()):
            fields[key] = metric(value, 'runnable_tasks', '/proc/loadavg', 0, number(value))
    except OSError:
        pass
    memory = {}
    for line in text_file('/proc/meminfo').splitlines():
        match = re.fullmatch(r'(MemTotal|MemAvailable):\s+(\d+) kB', line)
        if match: memory[match[1]] = int(match[2]) * 1024
    for key, name in (('memory_total_bytes', 'MemTotal'), ('memory_available_bytes', 'MemAvailable')):
        value = memory.get(name)
        fields[key] = metric(value, 'bytes', '/proc/meminfo:' + name, 0, type(value) is int and value >= 0)
    try:
        value = float(text_file('/proc/uptime').split()[0])
        fields['uptime_seconds'] = metric(value, 's', '/proc/uptime', 0, number(value) and value >= 0)
    except (ValueError, IndexError): pass
    temperatures = []
    for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
        name = text_file(zone / 'type')
        try: value = int(text_file(zone / 'temp')) / 1000
        except ValueError: continue
        if name.startswith(('cpub', 'cpul')) and -50 <= value <= 150:
            temperatures.append(value)
    fields['cpu_max_temperature_c'] = metric(max(temperatures) if temperatures else None, 'degC',
                                            'maximum_of_reported_cpu_thermal_zones', 0, bool(temperatures))
    fields['cpu_busy_percent'] = metric(unit='%', source='/proc/stat:counter_delta', reason='needs_two_counter_samples')
    try:
        row = text_file('/proc/stat').splitlines()[0].split()
        counters = list(map(int, row[1:9])) if row[0] == 'cpu' else []
        if len(counters) == 8:
            total, idle, monotonic = sum(counters), counters[3] + counters[4], time.monotonic()
            with _cpu_lock:
                previous, _cpu_previous = _cpu_previous, (total, idle, monotonic)
            if previous and .25 <= monotonic - previous[2] <= 10 and total > previous[0] and 0 <= idle - previous[1] <= total - previous[0]:
                busy = 100 * (1 - (idle - previous[1]) / (total - previous[0]))
                fields['cpu_busy_percent'] = metric(round(busy, 1), '%', '/proc/stat:counter_delta', 0, True)
    except (ValueError, IndexError): pass
    for key in ('load_1m', 'load_5m', 'load_15m', 'uptime_seconds'):
        fields.setdefault(key, metric(source='local_kernel'))
    # TCPM CURRENT_NOW is a negotiated current limit, not measured draw.
    # This board has no identified current/voltage measurement provider.
    for key, unit in (('board_current_a', 'A'), ('usb_port_current_a', 'A'), ('input_voltage_v', 'V')):
        fields[key] = metric(unit=unit, source='hardware_inventory', reason='no_measured_sensor_identified')
    return fields


def build_snapshot(flight, health, phone, wifi=None, performance=None, performance_stamp=None, now=None, pi=None, services=None, vision=None):
    now = time.time() if now is None else now
    h743 = {}
    heartbeat_age = clock_age(flight.get('last_heartbeat_unix'), now)
    heartbeat_fresh = (flight.get('connected') is True and flight.get('fresh') is True
                       and heartbeat_age is not None and heartbeat_age <= 2000)
    h743['connected'] = metric(heartbeat_fresh, 'bool', 'HEARTBEAT', heartbeat_age, heartbeat_fresh)
    for key in ('armed', 'mode', 'system_status'):
        value = flight.get(key)
        valid = type(value) is bool if key == 'armed' else isinstance(value, str) and value not in ('', 'unknown')
        h743[key] = metric(value if key == 'armed' else display_text(value, 32), 'bool' if key == 'armed' else 'text', 'HEARTBEAT', heartbeat_age, heartbeat_fresh and valid)
    mapping = (
        ('board_voltage_v', 'POWER_STATUS', 'board_voltage_v', 'V', 5000),
        ('servo_voltage_v', 'POWER_STATUS', 'servo_voltage_v', 'V', 5000),
        ('power_flags', 'POWER_STATUS', 'power_flags', 'MAV_POWER_STATUS', 5000),
        ('groundspeed_mps', 'VFR_HUD', 'groundspeed_mps', 'm/s', 1000),
        ('airspeed_mps', 'VFR_HUD', 'airspeed_mps', 'm/s', 1000),
        ('climb_mps', 'VFR_HUD', 'climb_mps', 'm/s', 1000),
        ('altitude_msl_m', 'VFR_HUD', 'altitude_m', 'm_MSL', 1000),
        ('relative_altitude_m', 'GLOBAL_POSITION_INT', 'relative_altitude_m', 'm', 1000),
        ('latitude_deg', 'GLOBAL_POSITION_INT', 'latitude', 'deg', 1000),
        ('longitude_deg', 'GLOBAL_POSITION_INT', 'longitude', 'deg', 1000),
        ('heading_deg', 'GLOBAL_POSITION_INT', 'heading_deg', 'deg', 1000),
        ('roll_deg', 'ATTITUDE', 'roll_deg', 'deg', 1000),
        ('pitch_deg', 'ATTITUDE', 'pitch_deg', 'deg', 1000),
        ('yaw_deg', 'ATTITUDE', 'yaw_deg', 'deg', 1000),
        ('gps_fix_type', 'GPS_RAW_INT', 'fix_type', 'GPS_FIX_TYPE', 2000),
        ('gps_satellites', 'GPS_RAW_INT', 'satellites', 'count', 2000),
        ('gps_hdop', 'GPS_RAW_INT', 'hdop', 'dimensionless', 2000),
        ('gps_horizontal_accuracy_m', 'GPS_RAW_INT', 'horizontal_accuracy_m', 'm', 2000),
        ('rc_rssi_raw', 'RC_CHANNELS', 'rssi', 'device_dependent_not_dBm', 2000),
        ('rc_channels_count', 'RC_CHANNELS', 'chancount', 'count', 2000),
    )
    for key, kind, name, unit, ttl in mapping:
        h743[key] = record_field(flight, kind, name, unit, now, ttl)
    fix = h743['gps_fix_type']
    if not (fix['fresh'] and type(fix['value']) is int and 3 <= fix['value'] <= 8):
        for key in ('latitude_deg', 'longitude_deg'):
            h743[key] = metric(unit='deg', source='GLOBAL_POSITION_INT', reason='no_independently_fresh_3D_GPS_fix')
    battery = flight.get('battery', {})
    if not isinstance(battery, dict): battery = {}
    battery_age = clock_age(battery.get('updated_unix'), now)
    identity = flight.get('h743_source', {})
    battery_identity_ok = (isinstance(identity, dict)
                           and type(identity.get('system_id')) is int and type(identity.get('component_id')) is int
                           and battery.get('source_system_id') == identity['system_id']
                           and battery.get('source_component_id') == identity['component_id'])
    for key, name, unit, maximum in (
        ('battery_voltage_v', 'voltage_v', 'V', 1000), ('battery_current_a', 'current_a', 'A', 10000),
        ('battery_remaining_percent', 'remaining_percent', '%', 100), ('battery_consumed_mah', 'consumed_mah', 'mAh', 10000000)):
        value = battery.get(name)
        fresh = (heartbeat_fresh and battery_identity_ok and battery.get('fresh') is True and battery.get('battery_id') == 0
                 and isinstance(battery.get('message_type'), str)
                 and battery.get('message_type') in {'SYS_STATUS', 'BATTERY_STATUS'}
                 and battery_age is not None and battery_age <= 5000 and number(value) and 0 <= value <= maximum)
        h743[key] = metric(value, unit, 'primary_battery_slot_0.' + name, battery_age, fresh)
    voltage, current = h743['battery_voltage_v'], h743['battery_current_a']
    power_fresh = voltage['fresh'] and current['fresh']
    h743['battery_power_w'] = metric(voltage['value'] * current['value'] if power_fresh else None,
        'W', 'primary_battery_slot_0:voltage_times_current', battery_age, power_fresh)
    h743['ekf_flags'] = metric(unit='EKF_STATUS_FLAGS', source='EKF_STATUS_REPORT', reason='no_independent_sample_clock')
    h743['landed_state'] = metric(unit='MAV_LANDED_STATE', source='EXTENDED_SYS_STATE', reason='no_validated_source')
    h743['on_ground'] = metric(unit='bool', source='EXTENDED_SYS_STATE', reason='no_validated_source')
    ground = flight.get('ground_state', {})
    if isinstance(ground, dict):
        age = clock_age(ground.get('updated_unix'), now)
        state = ground.get('landed_state')
        identity_ok = (isinstance(identity, dict) and type(identity.get('system_id')) is int and type(identity.get('component_id')) is int
                       and ground.get('source_system_id') == identity['system_id'] and ground.get('source_component_id') == identity['component_id'])
        fresh = (heartbeat_fresh and ground.get('message_type') == 'EXTENDED_SYS_STATE'
                 and identity_ok
                 and ground.get('fresh') is True and age is not None and age <= 1000
                 and type(state) is int and 1 <= state <= 4)
        h743['landed_state'] = metric(state, 'MAV_LANDED_STATE', 'EXTENDED_SYS_STATE', age, fresh)
        h743['on_ground'] = metric(state == 1, 'bool', 'EXTENDED_SYS_STATE', age, fresh)
    rc_fields = [record_field(flight, 'RC_CHANNELS', f'chan{index}_raw', 'us', now, 2000) for index in range(1, 19)]
    rc = {'values': [item['value'] for item in rc_fields], 'fresh': [item['fresh'] for item in rc_fields],
          'age_ms': [item['age_ms'] for item in rc_fields], 'unit': 'us', 'source': 'RC_CHANNELS:0'}
    ranges = []
    records = flight.get('sensors', {})
    if isinstance(records, dict):
        for record in records.values():
            if not isinstance(record, dict) or record.get('message_type') != 'DISTANCE_SENSOR' or type(record.get('instance')) is not int:
                continue
            instance = record['instance']
            ranges.append({'id': instance, 'orientation': record_field(flight, 'DISTANCE_SENSOR', 'orientation', 'MAV_SENSOR_ORIENTATION', now, 1000, instance),
                           'distance_cm': record_field(flight, 'DISTANCE_SENSOR', 'current_distance', 'cm', now, 1000, instance)})
            if len(ranges) == 8: break
    pi = sample_pi() if pi is None else pi
    pi['api_alive'] = metric(True, 'bool', 'authenticated_display_api_response', 0, True)
    wifi = wifi if isinstance(wifi, dict) else {}
    current = wifi.get('current', {}) if isinstance(wifi.get('current', {}), dict) else {}
    signal = current.get('rssi_dbm')
    pi['wifi_rssi_dbm'] = metric(signal, 'dBm', 'wpa_supplicant:SIGNAL_POLL', 0, type(signal) is int and -120 <= signal < 0)
    ssid = current.get('ssid')
    pi['wifi_ssid'] = metric(ssid, 'text', 'wpa_supplicant:STATUS', 0, isinstance(ssid, str) and 0 < len(ssid) <= 32)
    performance = performance if isinstance(performance, dict) else {}
    age = clock_age(performance_stamp, now)
    active = performance.get('ai_process_active')
    pi['ai_process_active'] = metric(active, 'bool', 'performance_guard:file_publication_not_inference_health', age,
                                   type(active) is bool and age is not None and age <= 5000)
    state = 'process_reported_not_health_verified' if active is True else 'no_process_reported'
    pi['ai_state'] = metric(state, 'text', 'performance_guard:process_presence_only', age,
                           type(active) is bool and age is not None and age <= 5000)
    messages = recent_messages(flight, now)
    faults = []
    if not heartbeat_fresh:
        faults.append({'component': 'h743', 'severity': 'warning', 'code': 'H743_TELEMETRY_UNAVAILABLE',
                       'text': 'Pi API is responding; H743 heartbeat is unavailable or stale.', 'age_ms': heartbeat_age})
    services = bounded_services(services)
    if services.get('fresh') is True and services['units']:
        faults.append({'component': 'pi', 'severity': 'error', 'code': 'PI_SERVICE_FAILED',
                       'text': str(len(services['units'])) + ' relevant services failed; open the Pi menu for names.', 'age_ms': services.get('age_ms')})
    if services.get('fresh') is not True or services.get('sample_succeeded') is not True:
        faults.append({'component': 'pi', 'severity': 'info', 'code': 'PI_SERVICE_CHECK_UNAVAILABLE',
                       'text': 'Current failed-service inventory is unavailable or incomplete.', 'age_ms': services.get('age_ms')})
    payload = {'schema': 1, 'generated_unix_ms': int(now * 1000), 'updated_unix': now,
            'last_heartbeat_unix': flight.get('last_heartbeat_unix') if heartbeat_fresh else None,
            'connection_id': str(flight.get('connection_id') or '')[:64], 'authority': 'advisory_only',
            'h743': h743, 'pi': bounded_pi(pi), 'sensor_health': bounded_health(health), 'rangefinders': ranges, 'rc_channels': rc,
            'messages': messages, 'faults': faults[:10], 'pi_service_health': services, 'camera': bounded_camera(vision, now),
            'follow_location': bounded_phone(phone), 'position_source': 'GLOBAL_POSITION_INT_fused_with_fresh_3D_GPS_fix_required',
            'freshness_basis': 'local_arrival_not_sensor_acquisition_time',
            'mavlink_transmit': False, 'flight_control_authority': False}
    # Optional diagnostic detail yields to the display's bounded JSON memory.
    while len(json.dumps(payload, separators=(',', ':')).encode('utf-8')) > 12288:
        payload['payload_truncated'] = True
        if payload['camera']['detections']:
            payload['camera']['detections'].pop()
            payload['camera']['detections_truncated'] = True
        elif payload['messages']:
            payload['messages'].pop(0)
        elif payload['pi_service_health']['units']:
            payload['pi_service_health']['units'].pop()
        else:
            break  # All remaining fields have fixed, independently bounded shapes.
    return payload
