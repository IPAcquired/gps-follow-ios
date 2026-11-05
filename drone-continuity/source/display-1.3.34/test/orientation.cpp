#include "DisplayOrientation.h"
#include "Gesture.h"
#include <cassert>
#include <cstdio>
#include <cmath>
struct Point{double x,y;};
Point convert(const uint16_t* c,double rawX,double rawY,int w,int h){
  Point p={( ((c[4]&1)?rawY:rawX)-c[0])*w/c[1],( ((c[4]&1)?rawX:rawY)-c[2])*h/c[3]};
  if(c[4]&2)p.x=w-p.x;
  if(c[4]&4)p.y=h-p.y;
  return p;
}
int main(){unsigned count=0;
  for(unsigned flags=0;flags<8;++flags){uint16_t base[5]={250,3400,300,3300,uint16_t(flags)},derived[5];
    for(unsigned r=0;r<4;++r){orientedCalibration(base,r,derived);
      for(int x=400;x<3500;x+=373)for(int y=450;y<3500;y+=419){Point old=convert(base,x,y,480,320),actual=convert(derived,x,y,(r&1)?480:320,(r&1)?320:480),expected=old;
        if(r==0)expected={320-old.y,old.x};
        if(r==2)expected={old.y,480-old.x};
        if(r==3)expected={480-old.x,320-old.y};
        assert(std::fabs(actual.x-expected.x)<0.00001&&std::fabs(actual.y-expected.y)<0.00001);++count;
      }
    }
  }
  PortraitHit pad={12,178,296,164,16,113,448,111};uint16_t x,y;
  assert(portraitHit(pad,12,178,x,y)&&x==16&&y==113);
  assert(portraitHit(pad,307,341,x,y)&&x<464&&y<224);
  assert(!portraitHit(pad,308,341,x,y)&&!portraitHit(pad,12,342,x,y));count+=4;
  // Each native portrait tab reaches its same shared canonical action range.
  for(int tab=0;tab<5;++tab){PortraitHit b={int16_t(5+tab*63),440,59,34,int16_t(56+tab*94),292,0,0};
    for(int px=b.x;px<b.x+b.w;++px)assert(portraitHit(b,px,452,x,y)&&((int(x)-12)/94)==tab&&y>=278);
    ++count;}
  PortraitHit buttons[]={{12,113,296,37,200,129,0,0},{252,12,58,33,440,25,0,0},{12,327,90,36,80,222,0,0}};
  assert(!portraitAction(buttons,3,100,180,x,y)); // Blank Wi-Fi/Pi labels cannot trigger canonical actions.
  assert(!portraitAction(buttons,3,110,330,x,y)); // Gaps between buttons are inert.
  assert(portraitAction(buttons,3,90,335,x,y)&&x==80&&y==222);
  Gesture drag;drag.feed(100,true,95,335);drag.feed(200,true,110,335);auto release=drag.feed(260,false);
  assert(release.kind==TouchKind::Tap&&release.x==110&&!portraitAction(buttons,3,release.x,release.y,x,y));
  // Crossing a control boundary moves continuously in physical pixels and cannot
  // turn the discontinuous canonical action coordinates into an invented swipe.
  Gesture small;small.feed(500,true,306,125);small.feed(600,true,310,125);release=small.feed(660,false);
  assert(release.kind==TouchKind::Tap&&!portraitAction(buttons,3,release.x,release.y,x,y));
  count+=5;
  std::printf("orientation: %u assertions/traces passed\n",count);
}
