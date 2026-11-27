"""Compile the production CDC/session handlers with a deterministic host HAL."""
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parent
source=(root/"desktop_xiao/desktop.cpp").read_text()
def function(name):
    start=source.index("void "+name+"(")
    opening=source.index("{",start)
    depth=0
    for i in range(opening,len(source)):
        depth+=(source[i]=="{")-(source[i]=="}")
        if depth==0:return source[start:i+1]
    raise RuntimeError(name)

shim = r'''
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include <cstdlib>
#include <cerrno>
#include <cassert>
#include <string>
#include "desktop_xiao/protocol.h"
#include "desktop_xiao/led_sideband.h"
using namespace desktop;
uint16_t sentSeq=0, lastAck=0, lastEvent=0;
Slot slot, lastDelivered;
bool seenScreen=false,seenEvent=false,haveTimer=true,active=false,timeoutFlag=false,timingSelection=false;
uint32_t usbAt=0,screenAt=0,tick=0;
char outgoing[24][124]; uint8_t head=0,count=0;
uint8_t lastUp[57], lastUpLength=0;uint32_t lastUpAt=0;
bool ledPending=false;uint16_t ledSeq=0;
uint32_t totalFrames=0,badFrames=0,stuckCount=0,lostCount=0,ledChanges=0;
struct {lamps::Settings settings;lamps::Output applied;} lights;
void park(){} void armExchange(){sentSeq=slot.seq;} uint32_t time_us_32(){return ++tick;}
'''
unit = shim + '\n'.join(function(n) for n in ['endSession','sendLine','receive'])
unit += source[source.index('int nibble('):source.index('\n}\n\nvoid setup()')]
unit += r'''
void expect(const char*s){assert(count==1); assert(std::string(outgoing[head])==std::string(s)+"\n"); head=count=0;}
int main(){
  command("HELLO");expect("DESKTOP XIAO 1");
  command("LEDVER");expect("LEDVER 2 CONTINUOUS-RAINBOW");
  command("INFO");expect("INFO XIAO-PAIR-LIGHTS 1 PIO-DMA PWM");
  command("LED?");expect("LED 0 0 64 0 29 0 0 0 0 0 0 0");
  command("STATS");expect("STATS 0 0 0 0 0 0 0");
  command("CAPS");expect("CAPS PAIR 1");
  command("PUT 1 00");expect("ERROR INACTIVE");
  command("BEGIN");expect("READY");
  command("PUT 2 00");expect("BUSY");
  Request start{123,14,2,5,1};receive(start);assert(count==0);
  command("SYNC");expect("SYNC 123");command("PING");expect("PONG");
  command("PUT 123 ab");expect("ERROR SEQUENCE");
  command("PUT 65536 aa");expect("ERROR SEQUENCE");command("PUT 0 aa");expect("ERROR SEQUENCE");
  command("PUT 42 b");expect("ERROR PAYLOAD");command("PUT 42 xyzq");expect("ERROR PAYLOAD");
  command("PUT 42 abcD");expect("QUEUED 42");assert(slot.data[0]==0xab&&slot.data[1]==0xcd);
  command("PUT 42 abcd");expect("QUEUED 42");command("PUT 42 aacd");expect("BUSY");
  command("PUT 43 abcd");expect("BUSY");receive(start);assert(count==0&&!slot.offered);
  armExchange();receive(start);assert(slot.offered&&count==0);
  Request release{42,15,2,5,2};receive(release);assert(count==2);
  assert(std::string(outgoing[head])=="TOUCH 15 2 2 5\n"&&std::string(outgoing[head+1])=="ACK 42\n");
  count=head=0;receive(release);assert(count==0);
  command("PUT 42 abcd");expect("ACK 42");command("PUT 42 ddee");expect("ERROR SEQUENCE");
  command("PUT 65535 aa");expect("QUEUED 65535");command("END");expect("ENDED");
  assert(!slot.seq&&!lastDelivered.seq&&!active);
  command("BEGIN");expect("READY");receive(release);assert(!count);
  Request opaque{};opaque.upLength=57;memset(opaque.up,0xef,57);receive(opaque);
  assert(count==1&&strlen(outgoing[head])==118);
  assert(std::string(outgoing[head]).find("UP efef")==0);count=head=0;
  receive(opaque);assert(!count);tick+=250000;receive(opaque);assert(count==1);count=head=0;
  for(int i=0;i<25;i++)sendLine("MSG");
  expect("LOST");assert(!active&&!slot.seq);
  puts("PASS: firmware CDC identity, session, stale-event suppression, malformed/retried PUT, ACK after display response, reconnect and overflow.");
}
'''
with tempfile.TemporaryDirectory(prefix='wired-cdc-') as scratch:
    dist=Path(scratch)
    mock=dist/'verify_cdc.cpp'; mock.write_text(unit)
    native=dist/('verify_cdc.exe' if sys.platform=='win32' else 'verify_cdc')
    subprocess.run([sys.argv[1] if len(sys.argv)>1 else 'g++','-std=c++17','-Wall','-Wextra','-Werror',
                    '-I',root,mock,'-o',native],check=True)
    subprocess.run([native],check=True)
