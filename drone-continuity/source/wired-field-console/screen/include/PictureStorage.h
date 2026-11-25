#pragma once
#include <stddef.h>
#include <stdint.h>
#include <new>
#include <string.h>
#include "WidgetCache.h"
#include "DisplayOrientation.h"
#include <uzlib.h>
#ifdef ARDUINO_ARCH_ESP32
#include <esp_attr.h>
#else
#define RTC_SLOW_ATTR
#define IRAM_ATTR
#endif

// ESP32 RTC slow SRAM is accessible to both CPUs. Dedicated instruction SRAM
// accepts aligned 32-bit loads/stores; no byte access or memcpy is used there.
// Linker placement guarantees the buffers before networking or SD consumes heap.
namespace picturestore {
constexpr size_t SlowWords=1792, IramWords=1664, OtherWords=640, Bytes=16384;
static_assert((SlowWords+IramWords+OtherWords)*4==Bytes,"JPEG staging size");
RTC_SLOW_ATTR static volatile uint32_t slow[SlowWords];
IRAM_ATTR static volatile uint32_t instruction[IramWords];
static volatile uint32_t ordinary[OtherWords];
inline volatile uint32_t& word(size_t index){
  if(index<SlowWords)return slow[index];
  index-=SlowWords;if(index<IramWords)return instruction[index];
  return ordinary[index-IramWords];
}
inline uint8_t byte(size_t index){return uint8_t(word(index/4)>>((index%4)*8));}
inline void read(size_t offset,uint8_t* dst,size_t n){
  while(n){uint32_t v=word(offset/4);unsigned m=offset%4;do{*dst++=uint8_t(v>>(8*m));++offset;--n;}while(++m<4&&n);}
}
inline void write(size_t offset,const uint8_t* src,size_t n){
  while(n){auto& target=word(offset/4);uint32_t v=target;unsigned m=offset%4;
    do{unsigned shift=m*8;v=(v&~(uint32_t(255)<<shift))|(uint32_t(*src++)<<shift);++offset;--n;}while(++m<4&&n);target=v;}
}
inline void wipe(){for(size_t i=0;i<Bytes/4;i++)word(i)=0;}
inline bool selfTest(){
  const size_t offsets[]={0,SlowWords*4-2,SlowWords*4,(SlowWords+IramWords)*4-2,(SlowWords+IramWords)*4,Bytes-5};
  const uint8_t sample[]={0x9b,0,0xff,0x76,0xb4};uint8_t got[sizeof sample];bool ok=true;
  for(size_t off:offsets){write(off,sample,sizeof sample);read(off,got,sizeof got);ok=ok&&!memcmp(sample,got,sizeof got);}
  wipe();return ok;
}
struct InflateReader {uzlib_uncomp engine;size_t pos,end;};
struct Scratch{
  union {
    struct {uint32_t pool[1024];uint16_t colors[256];} jpeg;
    struct {uint16_t out[2049];InflateReader input;} tile;
  };
};
struct Menus{WidgetCache widgets;PortraitHit hits[80];};
union Shared {
  Menus menus;
  Scratch decoder;
  Shared():menus{}{}
};
extern Shared shared;
}
