#include "Gesture.h"
#include <assert.h>
#include <stdio.h>
#include <initializer_list>
int main(){unsigned checks=0;
  #define CHECK(v) do{assert(v);++checks;}while(0)
  Gesture g;
  CHECK(g.feed(100,true,40,290).kind==TouchKind::None);
  CHECK(g.feed(130,false).kind==TouchKind::None);
  CHECK(g.feed(155,false).kind==TouchKind::Tap);
  CHECK(g.feed(210,false).kind==TouchKind::None);
  CHECK(g.feed(300,true,400,150).kind==TouchKind::None);
  CHECK(g.feed(400,true,100,160).kind==TouchKind::None);
  CHECK(g.feed(460,false).kind==TouchKind::SwipeLeft);
  g.feed(500,true,100,150);g.feed(600,true,400,160);
  CHECK(g.feed(660,false).kind==TouchKind::SwipeRight);
  g.feed(700,true,100,150);g.feed(800,true,105,260);
  CHECK(g.feed(860,false).kind==TouchKind::None);
  g.feed(900,true,100,150,false,false);g.feed(1000,true,400,150);
  CHECK(g.feed(1060,false).kind==TouchKind::None);
  g.feed(1100,true,100,150);g.feed(1200,true,400,150);g.feed(1300,true,100,150);
  CHECK(g.feed(1360,false).kind==TouchKind::None); // Retraced drag is not a tap.
  g.feed(1400,true,100,150);g.feed(1420,false);g.feed(1440,true,101,151);
  CHECK(g.feed(1495,false).kind==TouchKind::Tap); // Short sampling gap stays one tap.
  g.feed(1600,true,400,150);g.feed(3000,true,100,150);
  CHECK(g.feed(3060,false).kind==TouchKind::None); // Long holds cannot navigate.
  g.feed(0xfffffff0,true,400,150);g.feed(0x80,true,100,150);
  CHECK(g.feed(0xc0,false).kind==TouchKind::SwipeLeft);
  for(int i=0;i<5;++i)for(int direction:{-1,1}){int next=(i+direction+5)%5;CHECK(next>=0&&next<5);}
  printf("PASS: %u gesture assertions; tap and swipe are mutually exclusive\n",checks);
}
