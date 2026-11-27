#pragma once
#include <stdint.h>
// Stored touch calibration always describes the original landscape (rotation 1).
// ST7796 MADCTL: r0=MX, r1=MV, r2=MY, r3=MX|MY|MV.
inline void orientedCalibration(const uint16_t* base,uint8_t rotation,uint16_t* out) {
  for(int i=0;i<5;++i)out[i]=base[i];
  const bool swap=base[4]&1,ix=base[4]&2,iy=base[4]&4;
  if(rotation==0||rotation==2){out[0]=base[2];out[1]=base[3];out[2]=base[0];out[3]=base[1];
    bool nx=rotation==0?!iy:iy,ny=rotation==0?ix:!ix;
    out[4]=uint16_t(!swap)|(uint16_t(nx)<<1)|(uint16_t(ny)<<2);
  }else if(rotation==3)out[4]=uint16_t(swap)|(uint16_t(!ix)<<1)|(uint16_t(!iy)<<2);
}
struct PortraitHit {int16_t x,y,w,h,tx,ty,tw,th;};
inline bool portraitHit(const PortraitHit& hit,uint16_t x,uint16_t y,uint16_t& tx,uint16_t& ty) {
  if(x<hit.x||y<hit.y||x>=hit.x+hit.w||y>=hit.y+hit.h)return false;
  tx=hit.tx+(int(x)-hit.x)*hit.tw/hit.w;ty=hit.ty+(int(y)-hit.y)*hit.th/hit.h;return true;
}
inline bool portraitAction(const PortraitHit* hits,uint8_t count,uint16_t x,uint16_t y,uint16_t& tx,uint16_t& ty){
  for(uint8_t i=0;i<count;++i)if(portraitHit(hits[i],x,y,tx,ty))return true;
  return false;
}
