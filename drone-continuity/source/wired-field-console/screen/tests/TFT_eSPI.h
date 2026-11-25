#pragma once
#include <cstddef>
#include <cstdint>
#include <Arduino.h>
constexpr unsigned TFT_BLACK=0, TFT_NAVY=1, TFT_WHITE=0xffff;
class TFT_eSPI {
public:
  uint16_t surface[480*296]{};unsigned wx=0,wy=0,ww=0;
  bool down=false;
  uint16_t x=0, y=0, lastColor=0;
  unsigned bars=0, clears=0, rows=0, rects=0, touchReads=0;
  void fillScreen(unsigned color) { ++clears;for(auto& p:surface)p=color; }
  void fillRect(unsigned px,unsigned py,unsigned w,unsigned h,unsigned c) {
    for(unsigned y=py;y<py+h&&y<296;y++)for(unsigned x=px;x<px+w&&x<480;x++)surface[y*480+x]=c;
    if(py>296)return;
    if(py==296 && h==24) ++bars;
    else if(py>=296)return;
    else if(px==0&&py==0&&w==480&&h==296&&c==0) ++clears;
    else { ++rects; lastColor=c; }
  }
  void setTextColor(unsigned,unsigned) {}
  void drawString(const char*,unsigned,unsigned,unsigned) {}
  void setAddrWindow(unsigned x,unsigned y,unsigned w,unsigned){wx=x;wy=y;ww=w;}
  void pushColors(uint16_t* d,unsigned n,bool) { ++rows;lastColor=*d;for(unsigned i=0;i<n;i++)if(wy+i/ww<296&&wx+i%ww<480)surface[(wy+i/ww)*480+wx+i%ww]=d[i]; }
  bool getTouch(uint16_t* a,uint16_t* b,uint16_t) { ++touchReads;*a=x;*b=y;return down; }
};
