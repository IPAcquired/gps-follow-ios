#include "desktop_xiao/led_sideband.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <set>
using namespace lamps;

static int delta(Output a, Output b) {
  return std::max({std::abs(int(a.r)-b.r),std::abs(int(a.g)-b.g),std::abs(int(a.b)-b.b)});
}
static Output pixel(unsigned hue,unsigned b) {
  auto v=rainbowPixel(uint16_t(hue%1536),uint8_t(b));
  return {v.r,v.g,v.b,0,0};
}
int main() {
  for (unsigned b=0;b<=255;++b) {
    for (unsigned h=0;h<1536;++h) {
      auto v=pixel(h,b);
      assert(std::max({v.r,v.g,v.b})==b);
      assert(delta(v,pixel(h+1,b))<=2);
    }
  }
  Settings s{3,0,255,0,1,2};
  uint32_t previousCycle=UINT32_MAX;
  int maximumJump=0;
  for (unsigned speed=1;speed<=100;++speed) {
    s.speed=uint8_t(speed);
    const uint32_t cycle=rainbowCycleMs(s.speed);
    assert(cycle<previousCycle);previousCycle=cycle;
    RainbowClock timer;
    Output prev=render(s,0,timer);
    assert(prev.r==255 && !prev.g && !prev.b);
    bool orange=false,purple=false,green=false,blue=false;
    std::set<uint32_t> colors;
    for(uint32_t ms=2;ms<=cycle+2;ms+=2) {
      auto v=render(s,ms,timer);
      assert(v.power==1 && v.y==255 && std::max({v.r,v.g,v.b})==255);
      maximumJump=std::max(maximumJump,delta(v,prev));
      colors.insert((uint32_t(v.r)<<16)|(uint32_t(v.g)<<8)|v.b);
      orange|=(v.r==255 && v.g>=50 && v.g<=110 && !v.b);
      purple|=(v.b==255 && v.r>=100 && v.r<=190 && !v.g);
      green|=(v.g==255 && v.r<12 && v.b<12);
      blue|=(v.b==255 && v.r<12 && v.g<12);
      prev=v;
    }
    assert(colors.size()>=400 && orange && purple && green && blue);
    assert(prev.r==255 && prev.g<=2 && prev.b<=2);
  }
  assert(maximumJump<=6);
  RainbowClock a,b;
  const uint32_t base=UINT32_MAX-899;
  for(uint32_t elapsed=0;elapsed<=2800;elapsed+=2) {
    s.speed=elapsed<1200?75:100;
    auto v=render(s,base+elapsed,a),w=render(s,elapsed,b);
    assert(delta(v,w)==0);
    if(elapsed==1220){
      s.speed=1;assert(delta(v,render(s,base+elapsed,a))==0);
      assert(delta(w,render(s,elapsed,b))==0);
    }
  }
  const std::array<RgbLight,11> expected={{{255,255,255},{255,0,0},{0,255,0},{0,0,255},{0,255,255},{255,0,255},
      {255,120,0},{255,65,0},{255,255,0},{75,0,130},{148,0,255}}};
  RainbowClock c;
  for(unsigned b=0;b<=255;++b)for(unsigned color=0;color<expected.size();++color)
    for(unsigned speed:{1u,29u,99u,100u})for(uint32_t at:{0u,2u,43u,1200000u,UINT32_MAX}) {
      s={1,uint8_t(color),uint8_t(b),0,uint8_t(speed),0};
      auto v=render(s,at,c);
      auto ref=expected[color];
      assert(v.r==ref.r*b/255&&v.g==ref.g*b/255&&v.b==ref.b*b/255&&v.power==(b!=0));
    }
  puts("PASS: all brightness levels and hues preserve peak; cyclic pixel deltas <=2; all 100 speed settings rotate through orange, green, blue, purple and red; 32-bit wrap and rate changes preserve hue; all 11 original solid colors stable.");
  printf("Fastest cycle %u ms; slowest %u ms; largest per-channel change at 2 ms = %d/255.\n",rainbowCycleMs(100),rainbowCycleMs(1),maximumJump);
}
