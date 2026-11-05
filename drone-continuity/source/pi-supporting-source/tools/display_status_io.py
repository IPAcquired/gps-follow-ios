"""Read complete serial JSON lines across arbitrary USB read boundaries."""
import json,time
class StatusReader:
    def __init__(self,port):self.port=port;self.buffer=bytearray()
    def read(self,seconds=8):
        deadline=time.monotonic()+seconds;next_request=0;request_id=time.monotonic_ns()&0x7fffffff
        while time.monotonic()<deadline:
            if time.monotonic()>=next_request:
                self.port.write((json.dumps({'action':'status','request_id':request_id})+'\n').encode());next_request=time.monotonic()+2
            chunk=self.port.read(min(8192,self.port.in_waiting or 1))
            self.buffer.extend(chunk)
            while b'\n' in self.buffer:
                raw,_,rest=self.buffer.partition(b'\n');self.buffer=bytearray(rest)
                try:
                    text=raw.decode('utf-8','replace');start=text.find('{"')
                    if start<0:continue
                    value,_=json.JSONDecoder().raw_decode(text[start:])
                except (ValueError,UnicodeError):continue
                if isinstance(value,dict) and 'firmware' in value and ('request_id' not in value or value['request_id']==request_id):return value
            if len(self.buffer)>32768:self.buffer.clear()
        raise TimeoutError('No complete status JSON in bounded interval')
