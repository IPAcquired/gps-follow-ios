"""Bounded local X11 capture for the authenticated private ESP32 route."""
import os, subprocess, threading, time
import struct,hashlib,collections
import io
import desktop_workspace
try:
    from PIL import ImageGrab,Image
    import numpy as np
except ImportError:
    ImageGrab=Image=np=None
os.environ.setdefault('XAUTHORITY','/home/drone/.Xauthority')
_frames=collections.OrderedDict()
_frames_lock=threading.Lock()
_LOCK=threading.Lock()
_last=0.0
WIDTH,HEIGHT=160,120

def encode_rows(frame,width,height):
    if len(frame)!=width*height*2:raise ValueError('Invalid image size')
    output=bytearray()
    for y in range(height):
        row=memoryview(frame)[y*width*2:(y+1)*width*2];packed=bytearray();i=0
        while i<width:
            run=1
            while i+run<width and run<128 and row[i*2:i*2+2]==row[(i+run)*2:(i+run)*2+2]:run+=1
            if run>=3:
                packed.append(128+run-1);packed.extend(row[i*2:i*2+2]);i+=run
            else:
                start=i;i+=1
                while i<width and i-start<128:
                    if i+2<width and row[i*2:i*2+2]==row[i*2+2:i*2+4]==row[i*2+4:i*2+6]:break
                    i+=1
                packed.append(i-start-1);packed.extend(row[start*2:i*2])
        output.extend(struct.pack('<H',len(packed)));output.extend(packed)
    return bytes(output)

def changed_rows(frame,width,height,viewport,base=''):
    if len(frame)!=width*height*2:raise ValueError('Invalid image size')
    signature=struct.pack('<6H',width,height,*viewport)
    identity=hashlib.sha256(signature+frame).hexdigest()[:32]
    with _frames_lock:
        prior=_frames.get(base)
        previous=prior[1] if prior and prior[0]==signature else None
        _frames[identity]=(signature,frame);_frames.move_to_end(identity)
        while len(_frames)>3:_frames.popitem(last=False)
    result=bytearray()
    for row in range(height):
        start=row*width*2;end=start+width*2
        if previous is not None and frame[start:end]==previous[start:end]:continue
        encoded=encode_rows(frame[start:end],width,1)
        result.extend(struct.pack('<H',row));result.extend(encoded)
    result.extend(b'\xff\xff')
    return bytes(result),identity

def geometry():
    env=os.environ.copy();env.update(DISPLAY=':0',XAUTHORITY='/home/drone/.Xauthority')
    parts=subprocess.run(['/usr/bin/xdotool','getdisplaygeometry'],env=env,capture_output=True,text=True,timeout=1,check=True).stdout.split()
    if len(parts)!=2:raise RuntimeError('Unknown desktop geometry')
    w,h=map(int,parts)
    if not 1<=w<=8192 or not 1<=h<=8192:raise RuntimeError('Unsupported desktop geometry')
    return w,h,env

def capture(width=320,height=240,zoom=1,cx=5000,cy=5000,with_viewport=False):
    if (width,height) not in {(320,240),(336,252),(320,480),(480,320),(320,436),(480,276)} or type(zoom) is not int or zoom not in (1,2,3,4):
        raise ValueError('Unsupported desktop view')
    if any(type(v) is not int or not 0<=v<=10000 for v in (cx,cy)):raise ValueError('Invalid view center')
    global _last
    if not _LOCK.acquire(timeout=.25): raise RuntimeError('Desktop capture busy')
    try:
        if (width,height) in desktop_workspace.SIZES:desktop_workspace.ensure_size(width,height)
        pause=.05-(time.monotonic()-_last)
        if pause>0:time.sleep(pause)
        _last=time.monotonic()
        image=ImageGrab.grab(xdisplay=':0') if ImageGrab is not None else None
        if image is not None:
            w,h=image.size;env=None
            if not 1<=w<=8192 or not 1<=h<=8192:raise RuntimeError('Unsupported desktop geometry')
        else:w,h,env=geometry()
        full=(width,height) in {(320,480),(480,320),(320,436),(480,276)}
        cw=max(1,(min(w,h*width//height) if full else w)//zoom)
        ch=max(1,(min(h,w*height//width) if full else h)//zoom)
        x=max(0,min(w-cw,round(w*cx/10000-cw/2)));y=max(0,min(h-ch,round(h*cy/10000-ch/2)))
        if image is not None:
            scaled=image.crop((x,y,x+cw,y+ch)).resize((width,height),Image.Resampling.LANCZOS).convert('RGB')
            pixels=np.asarray(scaled,dtype=np.uint16)
            frame=(((pixels[:,:,0]>>3)<<11)|((pixels[:,:,1]>>2)<<5)|(pixels[:,:,2]>>3)).astype('<u2').tobytes()
        else:
            result=subprocess.run(['/usr/bin/ffmpeg','-nostdin','-loglevel','error','-f','x11grab',
            '-probesize','32','-analyzeduration','0','-framerate','30','-i',':0',
            '-frames:v','1','-vf',f'crop={cw}:{ch}:{x}:{y},scale={width}:{height}:flags=lanczos','-pix_fmt','rgb565le','-threads','1','-f','rawvideo','pipe:1'],
                env=env,capture_output=True,timeout=2,check=True)
            frame=result.stdout
        if len(frame)!=width*height*2: raise RuntimeError('Incomplete desktop frame')
        viewport=(round(x*10000/max(1,w-1)),round(y*10000/max(1,h-1)),round((x+cw-1)*10000/max(1,w-1)),round((y+ch-1)*10000/max(1,h-1)))
        return (frame,viewport) if with_viewport else frame
    finally: _LOCK.release()

def point(x,y,click=False):
    if type(x) is not int or type(y) is not int or not 0<=x<=10000 or not 0<=y<=10000:
        raise ValueError('Desktop point outside frame')
    w,h,env=geometry()
    command=['/usr/bin/xdotool','mousemove',str(round(x*(w-1)/10000)),str(round(y*(h-1)/10000))]
    if click:command.extend(['click','1'])
    subprocess.run(command,env=env,capture_output=True,timeout=1,check=True)

def browser_frame():
    if ImageGrab is None:raise RuntimeError('Direct desktop capture package unavailable')
    with _LOCK:
        desktop_workspace.ensure_size(800,600)
        image=ImageGrab.grab(xdisplay=':0').convert('RGB')
        if not 1<=image.width<=8192 or not 1<=image.height<=8192:raise RuntimeError('Unsupported desktop geometry')
        image.thumbnail((960,720),Image.Resampling.LANCZOS)
        output=io.BytesIO();image.save(output,format='JPEG',quality=82)
        data=output.getvalue()
        if len(data)>1024*1024:raise RuntimeError('Oversized desktop image')
        return data,image.width,image.height
