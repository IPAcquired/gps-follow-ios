"""Offline, reversible update for the two reviewed local desktop broker modules."""
import argparse
import fcntl
import hashlib
import os
import stat
import tempfile
from pathlib import Path


CAPTURE_OLD = '''def browser_frame():
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
'''
CAPTURE_NEW = '''def _browser_image():
    if ImageGrab is None:raise RuntimeError('Direct desktop capture package unavailable')
    desktop_workspace.ensure_size(800,600)
    image=ImageGrab.grab(xdisplay=':0').convert('RGB')
    if not 1<=image.width<=8192 or not 1<=image.height<=8192:raise RuntimeError('Unsupported desktop geometry')
    image.thumbnail((960,720),Image.Resampling.LANCZOS)
    image.info.clear()
    return image


def _browser_jpeg(image):
    output=io.BytesIO()
    image.save(output,format='JPEG',quality=82)
    data=output.getvalue()
    if len(data)>1024*1024:raise RuntimeError('Oversized desktop image')
    return data


def browser_frame():
    with _LOCK:
        image=_browser_image()
        return _browser_jpeg(image),image.width,image.height


def _paired_frame(previous_signature):
    with _LOCK:
        image=_browser_image()
        signature=hashlib.sha256(struct.pack('>II',*image.size))
        signature.update(image.tobytes())
        digest=signature.digest()
        if previous_signature==digest:
            return None,image.width,image.height,digest,None
        output=io.BytesIO()
        image.save(output,format='PNG',compress_level=1)
        blob=output.getvalue()
        if len(blob)<=1024*1024:
            return blob,image.width,image.height,digest,'png'
        return _browser_jpeg(image),image.width,image.height,digest,'jpeg'


browser_frame.paired_frame = _paired_frame
'''
BROKER_OLD = '''            if action=='frame':
                image,width,height=self.capture()
'''
BROKER_NEW = '''            if action=='frame':
                paired=getattr(self.capture,'paired_frame',None)
                if value.get('lossless') is True and paired is not None:
                    cached=lease.get('paired_frame')
                    previous=cached[0] if cached and cached[1]==value.get('base') else None
                    image,width,height,signature,codec=paired(previous)
                    if image is None:
                        if not cached or previous!=signature:raise ValueError('Invalid unchanged capture')
                        identity=cached[1]
                    else:
                        if codec not in ('png','jpeg') or len(image)>1024*1024:raise ValueError('Invalid paired capture')
                        identity=hashlib.sha256(image).hexdigest()
                        lease['paired_frame']=(signature,identity)
                    result={'ok':True,'frame_id':identity,'width':width,'height':height,
                            'expires_seconds':max(0,int(lease['until']-self.clock()))}
                    if image is not None and value.get('base')!=identity:
                        result[codec]=base64.b64encode(image).decode()
                    return result
                image,width,height=self.capture()
'''

FILES = (
    ('desktop_capture.py','fc91bdc3a63029603c170c4024bcd67ab54b3243750833bb3ab38d76a1699c23',
     '0656bcd1e75c63415590aa6341d77de02c82c501e66461c0973cf3bd73b27f72',CAPTURE_OLD,CAPTURE_NEW),
    ('browser_desktop.py','2bebde1025eb128f9de5bb742cbc15b24d32a2a8277ce70e085246ae47653cc2',
     'f85622893891dca131daf19eeef13d2444c4641312651a2d43a9d263df0255a9',BROKER_OLD,BROKER_NEW),
)


def replace_file(path, data, metadata):
    fd,temp=tempfile.mkstemp(prefix='.capture-update-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            current=os.fstat(out.fileno())
            if (current.st_uid,current.st_gid)!=(metadata.st_uid,metadata.st_gid):
                os.fchown(out.fileno(),metadata.st_uid,metadata.st_gid)
            os.fchmod(out.fileno(),stat.S_IMODE(metadata.st_mode))
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        Path(temp).unlink(missing_ok=True)


def update(directory, mode):
    directory=Path(directory).resolve(strict=True)
    descriptor=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX)
        tasks=[]
        observed={}
        for name,old_hash,new_hash,old,new in FILES:
            path=directory/name
            metadata=path.lstat()
            if not stat.S_ISREG(metadata.st_mode):raise ValueError('Expected a regular file: '+name)
            before=path.read_bytes()
            digest=hashlib.sha256(before).hexdigest()
            if digest not in (old_hash,new_hash):raise ValueError('Unrecognized source hash: '+name)
            observed[name]='current' if digest==new_hash else 'original'
            if mode=='check' or (mode=='apply' and digest==new_hash) or (mode=='restore' and digest==old_hash):
                continue
            src,dst,wanted=(old,new,new_hash) if mode=='apply' else (new,old,old_hash)
            if before.count(src.encode())!=1:raise ValueError('Reviewed edit did not match: '+name)
            after=before.replace(src.encode(),dst.encode(),1)
            if hashlib.sha256(after).hexdigest()!=wanted:raise ValueError('Unexpected output: '+name)
            compile(after,name,'exec')
            tasks.append((path,before,after,metadata))
        if mode=='restore':tasks.reverse()
        for path,before,after,metadata in tasks:
            if path.read_bytes()!=before:raise ValueError('Concurrent source change: '+path.name)
            replace_file(path,after,metadata)
            os.fsync(descriptor)
            observed[path.name]='current' if mode=='apply' else 'original'
        return observed
    finally:
        os.close(descriptor)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('check','apply','restore'))
    parser.add_argument('directory',type=Path,help='Directory containing both installed broker modules')
    args=parser.parse_args()
    for filename,state in update(args.directory,args.mode).items():
        print(filename,state)
