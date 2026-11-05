"""Pure, bounded environmental evidence. No I/O, inference or flight authority.

Object labels are detector hypotheses, not ground truth. MAVLink distances have
local-arrival timestamps, not verified sensor-acquisition times. Neither proves
safe clearance or identifies a calibrated physical sensor.
"""
from collections import Counter
import hashlib
import json
import math
import time
from itertools import islice

LABELS = (
    'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck',
    'boat', 'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench',
    'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra',
    'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
    'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove',
    'skateboard', 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup', 'fork',
    'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange', 'broccoli',
    'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch', 'potted plant',
    'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard',
    'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book',
    'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush',
)
VISION_AUTHORITY = 'observation_only_no_flight_commands'
FLIGHT_AUTHORITY = 'read_only_no_mavlink_transmit'


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def age_ms(stamp, now, ttl):
    if not number(stamp) or stamp <= 0 or not 0 <= now - stamp <= ttl:
        return None
    return round((now - stamp) * 1000)


def summarize(vision, flight, now=None):
    """Recheck source clocks on every request; publication/ports never refresh data."""
    now = time.time() if now is None else now
    if not number(now) or now <= 0:
        raise ValueError('Invalid observation clock')
    vision = vision if isinstance(vision, dict) else {}
    flight = flight if isinstance(flight, dict) else {}
    captured, updated = vision.get('captured_unix'), vision.get('updated_unix')
    camera_age = age_ms(captured, now, 2)
    camera_fresh = (type(vision.get('schema')) is int and vision['schema'] == 1
        and vision.get('authority') == VISION_AUTHORITY and vision.get('status') == 'active'
        and vision.get('fresh') is True and camera_age is not None
        and number(updated) and captured <= updated <= now
        and isinstance(vision.get('detections'), list))
    objects = []
    rejected = 0
    if camera_fresh:
        for row in vision['detections'][:100]:
            if not isinstance(row, dict):
                rejected += 1
                continue
            cls, confidence, box = row.get('class_id'), row.get('confidence'), row.get('box')
            if (type(cls) is not int or not 0 <= cls < len(LABELS) or row.get('label') != LABELS[cls]
                    or not number(confidence) or not .35 <= confidence <= 1
                    or not isinstance(box, list) or len(box) != 4
                    or any(not number(v) or not 0 <= v <= 65535 for v in box)
                    or box[2] <= box[0] or box[3] <= box[1]):
                rejected += 1
                continue
            objects.append({'label': LABELS[cls], 'class_id': cls, 'confidence': confidence,
                            'box': list(box), 'basis': 'detector_hypothesis_not_verified_identity'})
        rejected += max(0, len(vision['detections']) - 100)
    source = flight.get('h743_source')
    flight_fresh = (type(flight.get('schema')) is int and flight['schema'] == 1
        and flight.get('authority') == FLIGHT_AUTHORITY and flight.get('fresh') is True
        and flight.get('connected') is True
        and age_ms(flight.get('last_heartbeat_unix'), now, 7) is not None
        and isinstance(source, dict)
        and all(type(source.get(k)) is int and 1 <= source[k] <= 255 for k in ('system_id', 'component_id'))
        and isinstance(flight.get('connection_id'), str) and 0 < len(flight['connection_id']) <= 128)
    ranges = []
    records = flight.get('sensors')
    if flight_fresh and isinstance(records, dict):
        for record in islice(records.values(), 64):
            if (not isinstance(record, dict) or record.get('message_type') != 'DISTANCE_SENSOR'
                    or record.get('source_system_id') != source['system_id']
                    or record.get('source_component_id') != source['component_id']
                    or type(record.get('source_system_id')) is not int
                    or type(record.get('source_component_id')) is not int
                    or record.get('fresh') is not True
                    or record.get('freshness_basis') != 'local_arrival_not_sensor_acquisition_time'
                    or record.get('identity_basis') != 'mavlink_message_slot_not_physical_hardware'
                    or type(record.get('instance')) is not int or not 0 <= record['instance'] <= 255):
                continue
            values, units, stamps = record.get('values'), record.get('units'), record.get('field_updated_unix')
            if not all(isinstance(x, dict) for x in (values, units, stamps)):
                continue
            names = ('current_distance', 'min_distance', 'max_distance', 'orientation')
            ages = [age_ms(stamps.get(k), now, 1) for k in names]
            if any(a is None for a in ages) or any(type(values.get(k)) is not int for k in names):
                continue
            low, high, dist, orient = (values[k] for k in ('min_distance', 'max_distance', 'current_distance', 'orientation'))
            if (any(units.get(k) != 'cm' for k in names[:3])
                    or units.get('orientation') != 'MAV_SENSOR_ORIENTATION_enum'
                    or not 0 <= low < high < 65535 or not max(1, low) <= dist <= high
                    or not 0 <= orient <= 255):
                continue
            quality = values.get('signal_quality')
            if quality is not None and (type(quality) is not int or not 2 <= quality <= 100
                    or age_ms(stamps.get('signal_quality'), now, 1) is None):
                continue
            ranges.append({'message_slot': record['instance'], 'reported_orientation_enum': orient,
                           'reported_direction': {0: 'forward', 25: 'downward'}.get(orient, 'other_or_unknown'),
                           'distance_m': dist / 100, 'reported_quality_percent': quality,
                           'data_age_ms': max(ages), 'arrival_unix': stamps['current_distance'],
                           'physical_sensor_and_calibration': 'unverified',
                           'freshness_basis': 'local_arrival_not_sensor_acquisition_time'})
    result = {
        'schema': 1, 'observed_unix': now,
        'status': 'partial_observations' if camera_fresh or ranges else 'no_fresh_environment_data',
        'camera': {'fresh': bool(camera_fresh), 'captured_unix': captured if camera_fresh else None,
                   'data_age_ms': camera_age if camera_fresh else None,
                   'objects': objects, 'rejected_detection_rows': rejected,
                   'empty_detection_result_is_clear_space': False},
        'reported_ranges': ranges,
        'coverage': 'partial' if camera_fresh or ranges else 'unknown',
        'scene_type': 'unknown', 'safe_clearance': 'unknown', 'object_distance_association': 'not_established',
        'c1_and_matrix_live_scans': 'no_validated_live_producers',
        'training': {'ground_truth_labels': False, 'eligible_for_weight_training': False,
                     'requires': 'reviewed_labels_source_provenance_and_validation'},
        'authority': {'flight_commands': False, 'parameter_writes': False, 'model_activation': False},
        'limits': ['advisory_snapshot_not_live_avoidance', 'no_complete_surroundings_or_collision_guarantee',
                   'detector_confidence_is_not_probability_of_correctness',
                   'reported_ranges_are_not_physical_sensor_qualification'],
    }
    identity = {'camera_capture': result['camera']['captured_unix'], 'objects': objects,
                'connection_id': flight.get('connection_id') if ranges else None,
                'ranges': [{k: v for k, v in row.items() if k != 'data_age_ms'} for row in ranges]}
    result['snapshot_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return result


def chat_evidence(summary):
    """Bounded structured context, with no coordinates or free-form sensor labels."""
    counts = Counter(row['label'] for row in summary['camera']['objects'])
    return {'snapshot_id': summary['snapshot_id'], 'observed_unix': summary['observed_unix'],
            'status': summary['status'], 'camera_fresh': summary['camera']['fresh'],
            'detector_hypotheses': dict(counts.most_common(8)),
            'reported_ranges': [{k: row[k] for k in ('message_slot', 'reported_direction', 'distance_m', 'data_age_ms')}
                                for row in summary['reported_ranges'][:8]],
            'safe_clearance': 'unknown', 'scene_type': 'unknown', 'object_distance_association': 'not_established',
            'scope': 'request_time_advisory_snapshot_not_current_control_or_ground_truth'}


def describe(summary):
    """Deterministic live-state answer: never make unseen surroundings sound clear."""
    if summary['status'] == 'no_fresh_environment_data':
        return ('I have no fresh camera or validated range observations on the Orange Pi, so the environment is unknown. '
                'A UART device name is not a measurement. I cannot claim obstacle detection or safe clearance.')
    pieces = []
    if summary['camera']['fresh']:
        counts = Counter(row['label'] for row in summary['camera']['objects'])
        if counts:
            pieces.append('The camera detector reports ' + ', '.join(f'{count} {label}' for label, count in counts.most_common(8))
                          + '; these are unverified class hypotheses, not identified people or confirmed obstacles.')
        else:
            pieces.append('A fresh camera frame has no accepted object detections; this does not mean the area is clear.')
    if summary['reported_ranges']:
        pieces.append('H743-reported range samples: ' + ', '.join(
            f"slot {r['message_slot']} {r['reported_direction']} {r['distance_m']:.2f} m"
            for r in summary['reported_ranges'][:8]) + '. Physical sensor identity, calibration and acquisition time are unverified.')
    return ' '.join(pieces) + ' This is a partial, request-time snapshot only. Safe clearance is unknown; I do not command flight.'
