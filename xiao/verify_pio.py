"""Trace the assembled RP2350 instructions with the configured DMA/shift policy."""
from dataclasses import dataclass
from pathlib import Path
from collections import deque
import re

header = (Path(__file__).parent/"desktop_xiao/desktop_link.pio.h").read_text()
programs = {name: [int(v,16) for v in re.findall(r"0x([a-f0-9]{4}),", code)]
            for name,code in re.findall(r"desktop_(\w+)_program_instructions\[\] = \{(.*?)\};",header,re.S)}

@dataclass
class Engine:
    program: str
    pc: int = 0
    x: int = 0
    osr: int = 0
    used: int = 32
    isr: int = 0
    filled: int = 0
    def tick(self, b):
        code = programs[self.program][self.pc]
        n = self.pc + 1
        if code in (0x2085,0x2005,0x2082,0x2002):
            if (b.cs if (code&31)==5 else b.sck)!=bool(code&128): return
        elif code==0x80a0:  # pull block with autopull
            if self.used>=8:
                if not b.tx: return
                self.osr=b.tx.popleft(); self.used=0
        elif code in (0x6020,0x6001):
            if self.used>=8:
                if not b.tx: return
                self.osr=b.tx.popleft(); self.used=0
            if code==0x6020: self.x=self.osr; self.used=32
            else:
                b.miso=self.osr>>31
                self.osr=(self.osr<<1)&0xffffffff
                self.used+=1
            if self.used>=8 and b.tx: self.osr=b.tx.popleft(); self.used=0
        elif code==0x4001:
            self.isr=(self.isr<<1)|b.mosi; self.filled+=1
            if self.filled==8: b.rx.append(self.isr); self.isr=0; self.filled=0
        elif code>>13==0:
            kind=(code>>5)&7
            take={0:True,2:self.x!=0,6:b.cs}[kind]
            if kind==2: self.x=(self.x-1)&0xffffffff
            if take: n=code&31
        elif code in (0xe080,0xe081): b.driven=bool(code&1)
        elif code&0xffe0==0xc000: b.flags.add(code&31)
        else: raise ValueError(hex(code))
        self.pc=n

class Bus:
    def __init__(self, data, cs):
        self.cs=cs; self.sck=self.mosi=self.miso=0; self.driven=False
        self.tx=deque([583,*[x<<24 for x in data],0])
        self.flags=set(); self.rx=bytearray()
        self.engines=[Engine("exchange"),Engine("gate")]
    def tick(self,n=7):
        for _ in range(n):
            for e in self.engines: e.tick(self)

def bits(data):
    return [x>>i&1 for x in data for i in range(7,-1,-1)]

mosi = bytes((i*119+79)&255 for i in range(73))
miso = bytes((i*73+101)&255 for i in range(73))
incoming, expected = bits(mosi)+[1],bits(miso)
for initial in (0,1):
    for k in (0,1,7,8,9,31,32,64,128,256,512,581,582,583,584,585):
        b=Bus(miso,initial); b.tick(); assert not b.driven
        b.cs=1; b.tick(); assert not b.driven
        b.cs=0; b.tick(); assert b.driven
        observed=[]
        for value in incoming[:k]:
            b.mosi=value; b.sck=1; b.tick(); observed.append(b.miso)
            b.sck=0; b.tick()
        b.cs=1; b.tick()
        assert not b.driven and 1 in b.flags
        assert observed[:584]==expected[:min(k,584)]
        assert b.rx==mosi[:min(k,584)//8]
        assert (0 in b.flags)==(k>=584) and (2 in b.flags)==(k>584)
        b.cs=0; b.tick(); assert not b.driven
print("PASS: 32 PIO traces, both CS startup levels, mode 1 bidirectional bytes, short/exact/extra clocks and independent MISO release.")
