"""Stage full desktop JPEGs and exact compressed dirty rectangles on capable screens."""
import io
import struct
import zlib
from dataclasses import dataclass
from PIL import Image,ImageChops
from display_model import Patch,desktop_updates

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
            small=image.resize((int(target.width*fraction),int(target.height*fraction)),Image.Resampling.LANCZOS)
            candidate=small.resize(image.size,Image.Resampling.BILINEAR)
        for quality in (73,60,46,34):
            out=io.BytesIO()
            candidate.save(out,"JPEG",quality=quality,subsampling=2,optimize=True,progressive=False)
            blob=out.getvalue()
            if len(blob)<=MAX_JPEG:
                header=struct.pack(">BHHHI",9,len(blob),*target.size,zlib.crc32(blob))
                return ObjectUpdate((0,0,*target.size),target.tobytes(),
                                    (header,)+chunks(10,blob)+(b"\x0b",),"jpeg",len(blob))
    raise ValueError("Desktop JPEG exceeded the bounded staging buffer.")

def dense_change(current,target):
    hi,lo=ImageChops.difference(current,target).split()
    mask=ImageChops.lighter(hi,lo)
    box=mask.getbbox()
    if box is None:return False
    if (box[2]-box[0])*(box[3]-box[1]) < target.width*target.height//5:return False
    sample=mask.resize((80,50),Image.Resampling.NEAREST)
    return sample.histogram()[0]<int(80*50*.78)

def zlib_updates(current,target,bounds=None):
    result=[]
    if bounds is None:
        left,top,right,bottom = 0,0,*target.size
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


def _solid_band(image):
    """Largest run of identical solid rows or columns; avoid per-pixel Python loops."""
    width, height = image.size
    best = (0, False, 0, 0)
    for vertical, plane in ((False, image), (True, image.transpose(Image.Transpose.TRANSPOSE))):
        across, count = plane.size
        stride = across*2
        raw = plane.tobytes()
        color = None
        begin = 0
        for index in range(count+1):
            row = raw[index*stride:(index+1)*stride]
            value = row[:2] if row and row == row[:2]*across else None
            if value != color:
                if color is not None:
                    score = (index-begin)*across
                    if score > best[0]:
                        best = (score, vertical, begin, index)
                begin, color = index, value
    return best


def band_updates(current, target, bounds, depth=0):
    left, top, right, bottom = bounds
    high, low = ImageChops.difference(current.crop(bounds), target.crop(bounds)).split()
    dirty = ImageChops.lighter(high, low).getbbox()
    if dirty is None:
        return []
    bounds = (left+dirty[0], top+dirty[1], left+dirty[2], top+dirty[3])
    left, top, right, bottom = bounds
    region = target.crop(bounds)
    w, h = region.size
    raw = region.tobytes()
    if raw == raw[:2]*(w*h):
        rect = left, top, w, h
        return [(0, Patch(rect,raw,struct.pack(">B4H",1,*rect)+raw[:2]))]
    if w*h <= 2048 or depth >= 12:
        return zlib_updates(current,target,bounds)
    area, vertical, begin, end = _solid_band(region)
    if not area:
        vertical = w >= h
        begin = end = (w if vertical else h)//2
    offset = left if vertical else top
    cuts = sorted(set((offset, offset+begin, offset+end, right if vertical else bottom)))
    result = []
    for start, stop in zip(cuts,cuts[1:]):
        box = (start,top,stop,bottom) if vertical else (left,start,right,stop)
        result.extend(band_updates(current,target,box,depth+1))
    return result


def exchanges(plan, burst):
    count = 0
    for _, item in plan:
        if isinstance(item, ObjectUpdate):
            barriers = 2 if item.kind == "jpeg" else 1
            count += barriers + (len(item.packets)-barriers+burst-1)//burst
        else:
            count += 1
    return count


def interactive_plan(current, target, plan, point, burst):
    """Prioritize genuine changed pixels without reducing text or full-frame quality."""
    if not plan:
        return plan
    def proximity(entry):
        x,y,w,h = entry[1].rect
        dx = max(x-px, px-(x+w-1), 0)
        dy = max(y-py, py-(y+h-1), 0)
        return dx*dx+dy*dy
    high,low = ImageChops.difference(current,target).split()
    bounds = ImageChops.lighter(high,low).getbbox()
    if not bounds:
        return plan
    px, py = point if point is not None else bounds[:2]
    if isinstance(plan[0][1],ObjectUpdate) and plan[0][1].kind=="jpeg":
        left,top,right,bottom = bounds
        # Admit at most one 2,048-pixel exact tile before staging a whole picture.
        # Bias the box inward at a menu edge, where the clickable rows begin.
        w,h = min(64,right-left), min(32,bottom-top)
        x = max(left,min(right-w,px-w//3))
        y = max(top,min(bottom-h,py-h//3))
        preview = zlib_updates(current,target,(x,y,x+w,y+h))
        return preview+plan
    def ready_cost(ordered):
        x=max(0,px-4);y=max(0,py-4)
        roi=(x,y,min(target.width,px+5),min(target.height,py+5))
        hi,lo=ImageChops.difference(current.crop(roi),target.crop(roi)).split()
        missing=ImageChops.lighter(hi,lo)
        if not missing.getbbox():return 0
        cost=0
        for entry in ordered:
            cost+=exchanges([entry],burst)
            left,top,w,h=entry[1].rect
            l,t,r,b=max(left,x),max(top,y),min(left+w,roi[2]),min(top+h,roi[3])
            if r>l and b>t:
                missing.paste(0,(l-x,t-y,r-x,b-y))
                if not missing.getbbox():return cost
        return cost
    ordered=sorted(plan,key=proximity)
    if ready_cost(plan)<ready_cost(ordered):ordered=plan
    if len(plan)>3:
        alternative = band_updates(current,target,bounds)
        alternate=sorted(alternative,key=proximity)
        if (exchanges(alternative,burst)<exchanges(plan,burst) and direct_cost(alternative)[1]<=direct_cost(plan)[1]
                and (point is None or ready_cost(alternate)<=ready_cost(ordered))):
            ordered = alternate
    # A small label can cross several tile seams. On a burst-capable direct
    # connection a single exact tile then needs fewer round trips.
    left, top, right, bottom = bounds
    if burst>1 and len(ordered)>1 and right-left<=128 and (right-left)*(bottom-top)<=2048:
        single = zlib_updates(current,target,bounds)
        old_records, old_size = direct_cost(ordered)
        new_records, new_size = direct_cost(single)
        # direct_cost includes one JSON envelope per record. Compare the actual
        # graphics bytes independently as several records can share an envelope.
        if (len(single)==1 and exchanges(single,burst)<exchanges(ordered,burst)
                and new_records<=old_records and new_size-69*new_records<=old_size-69*old_records
                and (point is None or ready_cost(single)<=ready_cost(ordered))):
            return single
    return ordered


def select_plan(current,target,start,initial,capabilities,*,direct_usb=False,jpeg_background=None):
    compare_exact = direct_usb and not initial and capabilities&1
    if capabilities&4 and (initial or dense_change(current,target)):
        baseline = [(0,jpeg_scene(target if jpeg_background is None else jpeg_background))]
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
