"""Desktop pixels and touch coordinates for the negotiated screen viewport."""
import struct
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass,field,replace
from PIL import Image, ImageChops, ImageDraw

WIDTH, HEIGHT = 480, 296
LANDSCAPE=(WIDTH,HEIGHT)
PORTRAIT=(320,456)
TILE_W, TILE_H = 17, 12
CLEAR, HEARTBEAT = b"\x03", b"\x04"
POINTER_RANGE = 65534


def _pointer_stamp():
    shape = ((0, 0), (0, 13), (4, 10), (7, 15), (9, 14), (6, 9), (12, 9))
    bits = Image.new("LA", (13, 16))
    ImageDraw.Draw(bits).polygon(shape, fill=(255, 255), outline=(0, 0))
    mask = Image.new("1", bits.size)
    ImageDraw.Draw(mask).polygon(shape, fill=1)
    return bits, mask


_POINTER, _POINTER_MASK = _pointer_stamp()


def rgb565(image):
    red, green, blue = image.convert("RGB").split()
    high = ImageChops.add(red.point([v & 0xF8 for v in range(256)]),
                          green.point([v >> 5 for v in range(256)]))
    low = ImageChops.add(green.point([(v & 0x1C) << 3 for v in range(256)]),
                         blue.point([v >> 3 for v in range(256)]))
    return Image.merge("LA", (high, low))


@dataclass(frozen=True)
class Viewport:
    x: int
    y: int
    w: int
    h: int
    source_box:tuple=None
    native:object=field(default=None,compare=False,repr=False)
    pointer:tuple=field(default=None,compare=False,repr=False)
    pointer_box:tuple=field(default=None,compare=False,repr=False)

    def point(self, x, y):
        if not self.x <= x < self.x + self.w or not self.y <= y < self.y + self.h:
            return None
        px=(x-self.x)/max(1,self.w-1);py=(y-self.y)/max(1,self.h-1)
        if self.source_box:
            left,top,width,height,fullw,fullh=self.source_box
            px=(left+px*(width-1))/max(1,fullw-1)
            py=(top+py*(height-1))/max(1,fullh-1)
        return round(px*10000),round(py*10000)


def fit_frame(image,*,native=False,source_box=None,surface=LANDSCAPE):
    width,height=surface
    factor = min(width / image.width, height / image.height)
    w, h = max(1, round(image.width * factor)), max(1, round(image.height * factor))
    area = Viewport((width - w) // 2, (height - h) // 2, w, h,source_box,image.convert("RGB") if native else None)
    canvas = Image.new("LA", surface)
    canvas.paste(rgb565(image.resize((w, h), Image.Resampling.LANCZOS)), (area.x, area.y))
    return canvas, area


def with_pointer(frame, view, position):
    if position is None:
        return frame, view
    px, py = (v / POINTER_RANGE for v in position)
    if view.source_box:
        left, top, w, h, full_w, full_h = view.source_box
        dx = round(px * (full_w - 1)) - left
        dy = round(py * (full_h - 1)) - top
        if not (0 <= dx < w and 0 <= dy < h):
            return frame, view
        px, py = dx / max(1, w-1), dy / max(1, h-1)
    x, y = round(px * (view.w-1)), round(py * (view.h-1))
    stamp, mask = _POINTER, _POINTER_MASK
    if x + stamp.width > view.w:
        x -= stamp.width-1
        stamp, mask = (img.transpose(Image.Transpose.FLIP_LEFT_RIGHT) for img in (stamp, mask))
    if y + stamp.height > view.h:
        y -= stamp.height-1
        stamp, mask = (img.transpose(Image.Transpose.FLIP_TOP_BOTTOM) for img in (stamp, mask))
    # Confine the glyph to the visible desktop, including unusually narrow viewports.
    box = (max(0, -x), max(0, -y), min(stamp.width, view.w-x), min(stamp.height, view.h-y))
    dest = view.x + max(0, x), view.y + max(0, y)
    marked = frame.copy()
    marked.paste(stamp.crop(box), dest, mask.crop(box))
    left, top = dest
    return marked, replace(view, pointer_box=(left, top, left+box[2]-box[0], top+box[3]-box[1]))


class Zoom:
    def __init__(self):
        self.level=1;self.cx=self.cy=.5
        self.revision=0

    def command(self,action):
        if action not in range(7):raise ValueError("Invalid viewport operation.")
        if action<=2:self.level=action+1
        else:
            dx,dy={3:(-1,0),4:(1,0),5:(0,-1),6:(0,1)}[action]
            self.cx+=dx/(4*self.level);self.cy+=dy/(4*self.level)
        half=.5/self.level
        self.cx=min(1-half,max(half,self.cx));self.cy=min(1-half,max(half,self.cy))
        self.revision+=1

    def background(self,frame,view):
        if self.level==1:return frame,view
        image=view.native
        if image is None:raise ValueError("Native desktop capture unavailable for zoom.")
        width,height=image.size;w=max(1,round(width/self.level));h=max(1,round(height/self.level))
        x=max(0,min(width-w,round(width*self.cx-w/2)));y=max(0,min(height-h,round(height*self.cy-h/2)))
        return fit_frame(image.crop((x,y,x+w,y+h)),source_box=(x,y,w,h,width,height),surface=frame.size)

    def project(self,frame,view):
        return with_pointer(*self.background(frame,view),view.pointer)


def synthetic_frame(pressed=False,*,surface=LANDSCAPE):
    image = Image.new("RGB", surface, "#152434")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 64, 175, 139), fill="#00cc66" if pressed else "#dd4422")
    left=surface[0]-176
    draw.rectangle((left, 156, left+95, 231), fill="#3377ee")
    return image


@dataclass
class Patch:
    rect: tuple
    data: bytes
    packet: bytes

    def apply(self, canvas):
        x, y, w, h = self.rect
        canvas.paste(Image.frombytes("LA", (w, h), self.data), (x, y))


def pattern_patches(current, target, _start=0):
    """Each button of the fixed pattern is a single, fully acknowledged rectangle."""
    for index,(x,y,w,h) in enumerate(((80,64,96,76),(target.width-176,156,96,76))):
        box=x,y,x+w,y+h
        pixels=target.crop(box).tobytes()
        if current.crop(box).tobytes()==pixels:
            continue
        color=pixels[:2]
        if pixels!=color*(w*h):
            raise ValueError("Unexpected synthetic pattern color.")
        packet=struct.pack(">B4H",1,x,y,w,h)+color
        yield index,Patch((x,y,w,h),pixels,packet)


def initial_background(target):
    sample = target.resize((120, 74), Image.Resampling.NEAREST)
    count, color = max(sample.getcolors(120 * 74))
    if color == (0, 0) or count < 120 * 74 // 3:
        return None
    data = bytes(color)
    return Patch((0, 0, *target.size), data * (target.width * target.height),
                 struct.pack(">B4H", 1, 0, 0, *target.size) + data)


def changed_row(before, after):
    if after == before:
        return None
    left, right = 0, len(after)
    while after[left:left+2] == before[left:left+2]:
        left += 2
    while after[right-2:right] == before[right-2:right]:
        right -= 2
    return left // 2, after[left:right]


def dirty_tiles(mask, bounds, start):
    """Return dirty tile indices in the same cyclic order as the wire planner."""
    width,height = mask.size
    cols = (width + TILE_W - 1) // TILE_W
    rows = (height + TILE_H - 1) // TILE_H
    first_col,first_row = bounds[0]//TILE_W,bounds[1]//TILE_H
    end_col = (bounds[2]+TILE_W-1)//TILE_W
    end_row = (bounds[3]+TILE_H-1)//TILE_H
    # One set pixel yields at least 255 / (17*12) in its tile's average.
    # Align the crop to the global tile grid, including partial edge tiles.
    crop = (first_col*TILE_W,first_row*TILE_H,min(width,end_col*TILE_W),min(height,end_row*TILE_H))
    binary = mask.crop(crop).point(_DIRTY_LEVELS)
    flags = binary.reduce((TILE_W,TILE_H)).tobytes()
    span = end_col-first_col
    indices = [(first_row+n//span)*cols+first_col+n%span for n,v in enumerate(flags) if v]
    pivot = bisect_left(indices,start % (cols*rows))
    return indices[pivot:]+indices[:pivot]


_DIRTY_LEVELS = [0]+[255]*255


def patches(current, target, start=0):
    """Yield only changed tile areas. Caller commits each after the device ACK."""
    high, low = ImageChops.difference(current, target).split()
    mask = ImageChops.lighter(high, low)
    bounds = mask.getbbox()
    if bounds is None:
        return
    changed = target.crop(bounds)
    if all(vmin == vmax for vmin, vmax in changed.getextrema()):
        x, y, right, bottom = bounds
        color = bytes(changed.getpixel((0, 0)))
        width, height = right - x, bottom - y
        yield start, Patch((x, y, width, height), color * (width * height),
                           struct.pack(">B4H", 1, x, y, width, height) + color)
        return
    cols = (target.width + TILE_W - 1) // TILE_W
    for index in dirty_tiles(mask, bounds, start):
        x, y = index % cols * TILE_W, index // cols * TILE_H
        w, h = min(target.width - x, TILE_W), min(target.height - y, TILE_H)
        box = (x, y, x + w, y + h)
        data = target.crop(box).tobytes()
        before = current.crop(box).tobytes()
        if data == before:
            continue
        if data == data[:2] * (w * h):
            yield index, Patch((x, y, w, h), data, struct.pack(">B4H", 1,x,y,w,h) + data[:2])
            continue
        stride = 2 * w
        changes = [changed_row(before[i:i+stride], data[i:i+stride]) for i in range(0, len(data), stride)]
        row = 0
        while row < h:
            if changes[row] is None:
                row += 1
                continue
            left, after = changes[row]
            width, run = len(after) // 2, 1
            if after == after[:2] * width:
                while row + run < h and changes[row + run] == changes[row]:
                    run += 1
                packet = struct.pack(">B4H", 1, x + left, y + row, width, run) + after[:2]
            else:
                packet = struct.pack(">BHHB", 2, x + left, y + row, width) + after
            yield index, Patch((x + left, y + row, width, run), after * run, packet)
            row += run


def desktop_updates(current,target,start=0):
    """Merge exact neighboring solid fills; row payloads retain every RGB565 pixel."""
    def merge(rectangles,vertical):
        groups=defaultdict(list)
        for x,y,w,h,color in rectangles:
            group=(x,w,color) if vertical else (y,h,color)
            groups[group].append((y,h) if vertical else (x,w))
        joined=[]
        for (axis,width,color),runs in groups.items():
            ordered=sorted(runs)
            first,length=ordered[0]
            for point,extent in ordered[1:]:
                if first+length==point:
                    length+=extent
                else:
                    joined.append((axis,first,width,length,color) if vertical else (first,axis,length,width,color))
                    first,length=point,extent
            joined.append((axis,first,width,length,color) if vertical else (first,axis,length,width,color))
        return joined
    solids=[];updates=[]
    for index,patch in patches(current,target,start):
        if patch.packet[0]==1:
            solids.append((*patch.rect,patch.data[:2]))
        else:
            updates.append((index,patch))
    for _ in range(2):
        before=len(solids);solids=merge(merge(solids,False),True)
        if len(solids)==before:break
    cols=(target.width+TILE_W-1)//TILE_W
    tiles=cols*((target.height+TILE_H-1)//TILE_H)
    for x,y,w,h,color in solids:
        index=(y//TILE_H)*cols+x//TILE_W
        updates.append((index,Patch((x,y,w,h),color*(w*h),struct.pack(">B4H",1,x,y,w,h)+color)))
    return sorted(updates,key=lambda item:(item[0]-start)%tiles)


class Gesture:
    def __init__(self):
        self.start = None
        self.invalid = False
        self.moved = False

    def feed(self, state, x, y, view):
        if state not in (1, 2):
            return None
        point = view.point(x, y) if view else None
        mapping = (view.x, view.y, view.w, view.h, view.source_box) if view else None
        if self.start is not None:
            sx, sy, _, initial_mapping = self.start
            self.invalid |= mapping != initial_mapping
            self.moved |= max(abs(x - sx), abs(y - sy)) >= 5
        if state == 1:
            if self.start is None and not self.invalid and point is not None:
                self.start = (x, y, point, mapping)
            self.invalid |= point is None
            return None
        start, invalid, moved = self.start, self.invalid, self.moved
        self.start, self.invalid, self.moved = None, False, False
        if not start or not point or invalid:
            return None
        sx, sy, (px, py), _ = start
        if max(abs(x - sx), abs(y - sy)) < 5:
            # The wire action contains endpoints only. A loop cannot be safely
            # reproduced as a drag between coincident points or as a click.
            if moved:
                return None
            return {"type":"tap", "x":point[0], "y":point[1], "button":"left"}
        return {"type":"drag","x":px,"y":py,"end_x":point[0],"end_y":point[1]}
