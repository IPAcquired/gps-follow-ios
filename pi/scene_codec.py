"""Stage full desktop JPEGs and exact compressed dirty rectangles on capable screens."""
import io
import struct
import zlib
from dataclasses import dataclass
from PIL import Image,ImageChops
from display_model import WIDTH,HEIGHT,Patch,desktop_updates

MAX_JPEG=16384

@dataclass
class ObjectUpdate:
    rect: tuple
    data: bytes
    packets: tuple
    kind: str
    encoded_size: int
    def apply(self,canvas):
        x,y,w,h=self.rect
        canvas.paste(Image.frombytes("LA",(w,h),self.data),(x,y))

def to_rgb(frame):
    hi,lo=frame.split()
    red=hi.point([(i&248)|((i>>5)&7) for i in range(256)])
    green=ImageChops.add(hi.point([(i&7)<<3 for i in range(256)]),lo.point([i>>5 for i in range(256)]))
    green=green.point([((i&63)<<2)|((i&63)>>4) for i in range(256)])
    blue=lo.point([((i&31)<<3)|((i&31)>>2) for i in range(256)])
    return Image.merge("RGB",(red,green,blue))

def chunks(opcode,data):
    return tuple(struct.pack(">BH",opcode,i)+data[i:i+37] for i in range(0,len(data),37))

def jpeg_scene(target):
    image=to_rgb(target)
    for fraction in (1,.70,.50,.33,.20):
        candidate=image
        if fraction<1:
            small=image.resize((int(WIDTH*fraction),int(HEIGHT*fraction)),Image.Resampling.LANCZOS)
            candidate=small.resize(image.size,Image.Resampling.BILINEAR)
        for quality in (73,60,46,34):
            out=io.BytesIO()
            candidate.save(out,"JPEG",quality=quality,subsampling=2,optimize=True,progressive=False)
            blob=out.getvalue()
            if len(blob)<=MAX_JPEG:
                header=struct.pack(">BHHHI",9,len(blob),WIDTH,HEIGHT,zlib.crc32(blob))
                return ObjectUpdate((0,0,WIDTH,HEIGHT),target.tobytes(),
                                    (header,)+chunks(10,blob)+(b"\x0b",),"jpeg",len(blob))
    raise ValueError("Desktop JPEG exceeded the bounded staging buffer.")

def dense_change(current,target):
    hi,lo=ImageChops.difference(current,target).split()
    mask=ImageChops.lighter(hi,lo)
    box=mask.getbbox()
    if box is None:return False
    if (box[2]-box[0])*(box[3]-box[1]) < WIDTH*HEIGHT//5:return False
    sample=mask.resize((80,50),Image.Resampling.NEAREST)
    return sample.histogram()[0]<int(80*50*.78)

def zlib_updates(current,target,bounds=None):
    result=[]
    if bounds is None:
        left,top,right,bottom = 0,0,WIDTH,HEIGHT
        tile_width,tile_height = 64,32
    else:
        left,top,right,bottom = bounds
        # The R3.3 receiver limits a decompressed tile to 2,048 RGB565 pixels.
        # Anchor bands at the actual change so narrow controls avoid grid seams.
        tile_width = min(right-left,128)
        tile_height = min(bottom-top,2048//tile_width)
    for y in range(top,bottom,tile_height):
        for x in range(left,right,tile_width):
            box=(x,y,min(x+tile_width,right),min(y+tile_height,bottom))
            portion=target.crop(box)
            high,low=ImageChops.difference(current.crop(box),portion).split()
            dirty=ImageChops.lighter(high,low).getbbox()
            if dirty is None:continue
            crop=portion.crop(dirty)
            w,h=crop.size;px,py=x+dirty[0],y+dirty[1]
            rect=px,py,w,h
            raw=crop.tobytes()
            if raw==raw[:2]*(w*h):
                item=Patch(rect,raw,struct.pack(">B4H",1,px,py,w,h)+raw[:2])
            elif h==1 and w<=17:
                item=Patch(rect,raw,struct.pack(">BHHB",2,px,py,w)+raw)
            else:
                packed=zlib.compress(raw,6 if bounds is not None else 3)
                if len(packed)>4128:raise ValueError("Bounding error in compressed tile.")
                head=struct.pack(">B5H",6,px,py,w,h,len(packed))
                item=ObjectUpdate(rect,raw,(head,)+chunks(7,packed),"zlib",len(packed))
            result.append((0,item))
    return result

def direct_cost(plan):
    records = size = 0
    for _, item in plan:
        packets = item.packets if isinstance(item, ObjectUpdate) else (item.packet,)
        records += len(packets)
        # Minimum outbound bytes in the shipped JSON-over-serial protocol:
        # 69 for the envelope and two hex characters for every authenticated byte.
        size += sum(69 + 2 * (21 + len(packet)) for packet in packets)
    return records, size


def select_plan(current,target,start,initial,capabilities,*,direct_usb=False):
    compare_exact = direct_usb and not initial and capabilities&1
    if capabilities&4 and (initial or dense_change(current,target)):
        baseline = [(0,jpeg_scene(target))]
        # First paint and zoom establish a fresh full canvas. An existing,
        # synchronized desktop can use exact RGB565 patches for a large dialog.
        if not compare_exact:
            return baseline
        colors = target.resize((60,37), Image.Resampling.NEAREST).getcolors(60*37)
        if max(count for count,_ in colors) < 60*37//4:
            return baseline
        alternatives = [zlib_updates(current,target)]
    else:
        baseline = desktop_updates(current,target,start)
        if not capabilities&1 or len(baseline)<=3:
            return baseline
        zipped = zlib_updates(current,target)
        count = sum(len(p.packets) if isinstance(p,ObjectUpdate) else 1 for _,p in zipped)
        if count<len(baseline):
            baseline = zipped
        if not compare_exact:
            return baseline
        alternatives = []
    high,low = ImageChops.difference(current,target).split()
    bounds = ImageChops.lighter(high,low).getbbox()
    if bounds:
        alternatives.append(zlib_updates(current,target,bounds))
    base_records,base_size = direct_cost(baseline)
    best = baseline
    best_cost = (base_records,base_size)
    for plan in alternatives:
        records,size = direct_cost(plan)
        if records < base_records and size*5 <= base_size*4 and (records,size)<best_cost:
            best,best_cost = plan,(records,size)
    return best
