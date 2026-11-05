"""Bounded SSH bridge frames; stale network queues cannot renew flight data."""
import base64
import binascii
import json
import math

def decode_frame(line, now, previous_sequence):
    if len(line)>8192:raise ValueError('Frame too large')
    try:
        value=json.loads(line)
        if type(value) is not dict or set(value)!={'seq','received_unix','data'}:raise ValueError('Frame fields')
        sequence,stamp=value['seq'],value['received_unix']
        if type(sequence) is not int or not previous_sequence<sequence<=2**53:raise ValueError('Sequence')
        if type(stamp) not in (float,int) or not math.isfinite(stamp) or not -1<=now-stamp<=2:raise ValueError('Stale frame')
        if type(value['data']) is not str or len(value['data'])>5464:raise ValueError('Payload size')
        data=base64.b64decode(value['data'],validate=True)
        if not 1<=len(data)<=4096:raise ValueError('Payload size')
        return sequence,data
    except (TypeError,OverflowError,RecursionError,binascii.Error) as exc:
        raise ValueError('Invalid frame') from exc
