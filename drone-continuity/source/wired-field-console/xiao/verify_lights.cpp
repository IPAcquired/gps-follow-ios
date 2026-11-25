#include "desktop_xiao/led_sideband.h"
#include <cassert>
#include <cstring>
#include <cstdio>
#include <initializer_list>
using namespace lamps;
void seal(uint8_t*w){desktop::write16(w+71,desktop::crc(w,71));}
int main(){
  Settings s;auto d=render(s,0);assert(!d.power&&!d.y);
  uint8_t w[73]{};memcpy(w,"DLQ1",4);w[4]=1;desktop::write16(w+5,37);
  w[7]=1;w[8]=1;w[9]=140;w[11]=29;w[12]=2;seal(w);Command q{};
  assert(parse(w,q)==Type::Request&&q.set&&!q.status&&q.seq==37);
  auto v=render(q.settings,0);assert(v.r==140&&!v.g&&!v.b&&v.y==140&&v.power);
  for(unsigned bit=0;bit<73*8;++bit){
    w[bit/8]^=1u<<(bit%8);Command n{};
    assert(parse(w,n)!=Type::Request);w[bit/8]^=1u<<(bit%8);
  }
  for(uint8_t mode=0;mode<6;++mode)for(uint8_t color=0;color<11;++color)
    for(uint8_t pattern=0;pattern<4;++pattern)for(uint8_t duty=0;duty<4;++duty){
      s={mode,color,137,pattern,62,duty};
      for(uint32_t now:{0U,31U,172U,2376U,0xffffffe0U}){
        auto p=render(s,now);auto ref=lightPattern(mode,color,137,now,pattern,62);
        assert(p.r==ref.r&&p.g==ref.g&&p.b==ref.b&&p.power==(mode!=0));
        if(duty==0)assert(!p.y);
        if(duty==1)assert(p.y==137);
        if(duty==3)assert(p.y==(now%lightPeriod(62)<lightPeriod(62)/2?137:0));
      }
    }
  for(auto index:{7,8,10,11,12}){
    uint8_t old=w[index];w[index]=255;seal(w);q={};assert(parse(w,q)==Type::Request&&q.status==1);w[index]=old;
  }
  memset(w,0,sizeof(w));memcpy(w,"DLP1",4);seal(w);q={};assert(parse(w,q)==Type::Poll);
  w[56]=1;seal(w);assert(parse(w,q)==Type::Invalid);
  reply(w,37,0,s,v);assert(!memcmp(w,"DLR1",4)&&desktop::read16(w+5)==37&&w[13]==140&&w[17]==1);
  assert(desktop::read16(w+71)==desktop::crc(w,71));
  puts("PASS: LED wire integrity/limits, settings receipt, 5,280 effect samples and yellow modes.");
}
