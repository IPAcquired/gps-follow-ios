#include "desktop_xiao/protocol.h"
#include <cassert>
#include <cstdio>
using namespace desktop;

int main() {
  assert(crc((const uint8_t*)"123456789", 9) == 0x29b1);
  uint8_t wire[FRAME]{};
  Slot s;
  reply(wire, s);
  assert(!memcmp(wire,"DTR1",4) && !wire[4] && read16(wire+71)==crc(wire,71));
  for (uint8_t n=1;n<=PAYLOAD;n++) {
    s.length=n; s.seq=0xfffe;
    for (unsigned i=0;i<n;++i) s.data[i]=uint8_t(i*9+51);
    reply(wire,s);
    assert(wire[4]==1 && read16(wire+5)==s.seq && read16(wire+7)==n);
    assert(!memcmp(wire+9,s.data,n) && read16(wire+71)==crc(wire,71));
    for (size_t i=9+n;i<BODY;++i) assert(wire[i]==0);
  }
  assert(!confirmed(s,0,0xfffe)); // idle response is not a fetch
  assert(!confirmed(s,0xfffe,0));
  assert(!confirmed(s,0xfffe,0));
  assert(confirmed(s,0xfffe,0xfffe));
  memset(wire,0,sizeof(wire));
  memcpy(wire,"DTQ1",4);
  wire[4]=2; write16(wire+5,479); write16(wire+7,295);
  write16(wire+9,65535); write16(wire+11,0xfffe);
  write16(wire+71, crc(wire,71));
  Request q;
  assert(parse(wire,q) && q.x==479 && q.y==295 && q.action==2 && q.event==65535 && q.ack==0xfffe);
  for (size_t b=0;b<FRAME*8;++b) {
    wire[b/8]^=1u<<(b%8); assert(!parse(wire,q)); wire[b/8]^=1u<<(b%8);
  }
  wire[20]=1; write16(wire+71,crc(wire,71)); assert(!parse(wire,q)); wire[20]=0;
  write16(wire+5,480); write16(wire+71,crc(wire,71)); assert(!parse(wire,q));
  write16(wire+5,0); write16(wire+7,296); write16(wire+71,crc(wire,71)); assert(!parse(wire,q));
  write16(wire+7,0); wire[4]=3; write16(wire+71,crc(wire,71)); assert(!parse(wire,q));
  wire[4]=0; write16(wire+71,crc(wire,71)); assert(parse(wire,q));
  for (unsigned n=1; n<=57; ++n) {
    memset(wire+13,0,BODY-13);wire[13]=n;
    for(unsigned i=0;i<n;++i) wire[14+i]=uint8_t(i+1);
    write16(wire+71,crc(wire,71));
    assert(parse(wire,q) && q.upLength==n && !memcmp(q.up,wire+14,n));
    if(n<57) {
      wire[14+n]=0x55;write16(wire+71,crc(wire,71));
      assert(!parse(wire,q));wire[14+n]=0;
    }
  }
  wire[13]=58; write16(wire+71,crc(wire,71));assert(!parse(wire,q));
  wire[13]=57;wire[4]=1;write16(wire+71,crc(wire,71));assert(!parse(wire,q));
  puts("PASS: 62 payload sizes, CRC reference and 584 single-bit corruptions, coordinates, reserved bytes, and delayed ACK.");
}
