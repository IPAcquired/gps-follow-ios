#include "XiaoLights.h"
#include <cassert>
#include <cstdio>
namespace wd=wireddesktop;
static bool plugged=true,corrupt=false,wrongSeq=false,blank=false;static uint8_t failSet=0;
static unsigned sets=0,gets=0;static uint8_t reply[76]{};
bool wiredDesktopExchange(uint8_t* q,uint8_t* r,size_t n){
  assert(n==73&&wd::get16(q+71)==wd::checksum(q,71));
  if(!plugged)return false;
  if(blank){memset(r,255,n);return true;}
  if(!memcmp(q,"DLQ1",4)){memset(reply,0,76);memcpy(reply,"DLR1",4);reply[11]=29;reply[9]=64;
    wd::put16(reply+5,wd::get16(q+5)+wrongSeq);
    if(q[4]==1){sets++;memcpy(reply+7,q+7,6);reply[4]=failSet;}else gets++;
    wd::put16(reply+71,wd::checksum(reply,71)^corrupt);memset(r,0,n);return true;}
  assert(!memcmp(q,"DLP1",4));memcpy(r,reply,n);return true;
}
int main(){
  XiaoLights l;auto step=[&](unsigned elapsed){fakeNow+=elapsed;l.service(false);};
  auto poll=[&](){step(1);step(7);};
  assert(!l.ready());l.probe();poll();assert(l.ready()&&gets==1);
  auto c=l.confirmed;c.mode=4;c.color=3;c.yellow=2;c.pattern=1;c.speed=56;
  assert(l.set(c));assert(!l.set(c));assert(!l.confirmed.mode);poll();assert(l.confirmed.mode==4&&l.confirmed.yellow==2&&sets==1);
  unsigned rev=l.revision;step(800);assert(l.revision==rev&&sets==1);
  c.mode=6;assert(!l.set(c));c.mode=3;
  corrupt=true;assert(l.set(c));poll();step(76);step(76);assert(l.ready()&&!l.pending()&&l.confirmed.mode==4&&l.applyError==XiaoLights::ApplyError::NoReply);
  corrupt=false;wrongSeq=true;l.probe();poll();step(76);step(76);assert(l.ready()&&!l.pending());
  wrongSeq=false;l.probe();poll();assert(l.ready()&&l.applyError==XiaoLights::ApplyError::NoReply);
  failSet=1;assert(l.set(c));poll();assert(l.ready()&&!l.pending()&&l.applyError==XiaoLights::ApplyError::Rejected);
  failSet=2;assert(l.set(c));poll();assert(l.ready()&&!l.pending()&&l.applyError==XiaoLights::ApplyError::Driver);failSet=0;
  // A tap during the menu's automatic GET is promoted to an absolute SET.
  l.probe();step(1);unsigned previousSets=sets;assert(l.set(c));poll();
  assert(sets==previousSets+1&&l.confirmed.mode==3&&l.applyError==XiaoLights::ApplyError::None);
  c.color=2;assert(l.set(c));auto second=l.editBase();second.yellow=1;assert(l.set(second));
  auto third=l.editBase();third.brightness=48;assert(l.set(third));poll();poll();
  assert(l.confirmed.color==2&&l.confirmed.yellow==1&&l.confirmed.brightness==48);
  // A single corrupt receipt recovers without blinking the disconnected UI.
  c=l.confirmed;c.speed=67;corrupt=true;assert(l.set(c));poll();corrupt=false;step(76);step(7);
  assert(l.ready()&&l.confirmed.speed==67&&!l.pending());
  plugged=false;step(2400);assert(!l.ready()&&!l.set(c));
  unsigned offlineSets=sets;plugged=true;l.probe();poll();assert(l.ready()&&sets==offlineSets);
  auto attempt=[&](){l.probe(true);step(1);step(16);step(75);step(16);step(75);step(550);};
  l.beginDetachWatch();plugged=false;
  for(unsigned i=0;i<6;++i)attempt();assert(!l.physicallySilent()); // Busy SD mutex, zero wire observations.
  plugged=true;corrupt=true;
  for(unsigned i=0;i<6;++i)attempt();assert(!l.physicallySilent()); // The helper is still physically answering.
  corrupt=false;blank=true;attempt();assert(!l.physicallySilent());
  for(unsigned i=0;i<4;++i)attempt();assert(l.physicallySilent());
  blank=false;attempt();assert(!l.physicallySilent()&&l.ready()&&sets==offlineSets);
  puts("PASS confirmed settings, bounded retry, USB-independent menu edits, periodic probe preemption, rapid adjustments, dropout grace, genuine unplug and read-only reattachment.");
}
