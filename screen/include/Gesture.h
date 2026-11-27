#pragma once
#include <stdint.h>
#include <stdlib.h>
enum class TouchKind { None, Tap, SwipeLeft, SwipeRight };
struct TouchResult {TouchKind kind=TouchKind::None;uint16_t x=0,y=0;};
class Gesture {
 public:
  bool active=false;
  TouchResult feed(uint32_t now,bool down,uint16_t x=0,uint16_t y=0,bool navigate=true,bool tap=true) {
    TouchResult result;
    if(down) {
      if(!active){active=true;started=now;sx=ex=x;sy=ey=y;dxMax=dyMax=0;navAllowed=navigate;tapAllowed=tap;}
      ex=x;ey=y;last=now;
      int dx=abs(int(x)-sx),dy=abs(int(y)-sy);
      if(dx>dxMax)dxMax=dx;
      if(dy>dyMax)dyMax=dy;
      return result;
    }
    if(!active||uint32_t(now-last)<55)return result;
    active=false;uint32_t duration=uint32_t(last-started);int dx=int(ex)-sx;
    result.x=ex;result.y=ey;
    if(navAllowed&&duration>=60&&duration<=1200&&abs(dx)>=72&&dyMax<=45)
      result.kind=dx<0?TouchKind::SwipeLeft:TouchKind::SwipeRight;
    else if(tapAllowed&&duration<=900&&dxMax<=18&&dyMax<=18)result.kind=TouchKind::Tap;
    return result;
  }
 private:
  bool navAllowed=false,tapAllowed=false;
  uint32_t started=0,last=0;
  uint16_t sx=0,sy=0,ex=0,ey=0;int dxMax=0,dyMax=0;
};
