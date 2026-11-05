import sys,pathlib,random,struct,json
sys.path.insert(0,str(pathlib.Path(__file__).parent/'pi-field-candidate'))
from desktop_capture import encode_rows
rng=random.Random(1316)
for n in range(10000):
 w=320 if n%2 else 480
 pixels=[rng.randrange(65536) for _ in range(w)] if n%3 else [n%65536]*w
 raw=struct.pack('<'+'H'*w,*pixels);encoded=encode_rows(raw,w,1)
 size=struct.unpack('<H',encoded[:2])[0];assert size==len(encoded)-2 and size<=w*2+8
 decoded=bytearray();i=2
 while i<len(encoded):
  c=encoded[i];i+=1;count=(c&127)+1
  if c&128:decoded.extend(encoded[i:i+2]*count);i+=2
  else:decoded.extend(encoded[i:i+count*2]);i+=count*2
 assert decoded==raw
print(json.dumps({'lossless_encoder_roundtrips':10000,'passed':True}))
