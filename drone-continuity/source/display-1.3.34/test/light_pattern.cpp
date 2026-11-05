#include "LightPattern.h"
#include <cassert>
int main(){
 assert(lightPeriod(1)==10000&&lightPeriod(80)==100&&lightPeriod(99)==24&&lightPeriod(100)==0);
 for(int speed=2;speed<100;++speed)assert(lightPeriod(speed)<lightPeriod(speed-1));
 for(unsigned i=0;i<10000;++i){
  uint8_t speed=1+i%100,brightness=i%256,color=i%LIGHT_COLOR_COUNT;
  auto off=lightPattern(0,color,brightness,i,0,speed);assert(!off.r&&!off.g&&!off.b);
  auto white=lightPattern(5,color,brightness,i,0,speed);assert(white.r==brightness&&white.g==brightness&&white.b==brightness);
  for(int mode=1;mode<5;++mode){auto c=lightPattern(mode,color,brightness,i,i%4,speed);assert(c.r<=brightness&&c.g<=brightness&&c.b<=brightness);}
 }
 for(unsigned speed=1;speed<100;++speed){
  unsigned period=lightPeriod(speed);
  for(unsigned pattern=0;pattern<4;++pattern){
   auto on=lightPattern(4,1,128,period*2+1,pattern,speed);
   auto off=lightPattern(4,1,128,period*2+(speed>=60?period/2:period*3/10),pattern,speed);
   assert(on.r||on.g||on.b);assert(!off.r&&!off.g&&!off.b);
  }
  auto peak=lightPattern(2,1,128,period,0,speed);assert(peak.r==128);
  auto end=lightPattern(2,1,128,period*2,0,speed);assert(!end.r);
 }
 for(unsigned mode=1;mode<6;++mode)for(unsigned color=0;color<LIGHT_COLOR_COUNT;++color){
  auto first=lightPattern(mode,color,128,0,3,100);
  for(unsigned t=1;t<20000;t+=113){auto value=lightPattern(mode,color,128,t,3,100);assert(value.r==first.r&&value.g==first.g&&value.b==first.b);}
 }
 for(uint8_t initial=0;initial<6;++initial){uint8_t mode=initial,pattern=2;selectBeacon(mode,pattern);assert(mode==4);assert(pattern==(initial==4?3:2));}
 assert(lightAdjustment(40)==-10&&lightAdjustment(135)==-1&&lightAdjustment(240)==0&&lightAdjustment(340)==1&&lightAdjustment(430)==10);
}
