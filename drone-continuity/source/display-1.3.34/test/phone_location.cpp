#include "PhoneLocation.h"
#include <cassert>
#include <cstdio>
#include <cstring>
int main(){
  assert(phoneLocationValues(1,0,0,0,0,1));assert(phoneLocationValues(UINT32_MAX-1,1,1000,-90,180,30));
  assert(!phoneLocationValues(1,1,0,0,0,1));assert(!phoneLocationValues(0,0,0,0,0,1));assert(!phoneLocationValues(UINT32_MAX,1,0,0,0,1));
  assert(!phoneLocationValues(2,1,1001,0,0,1));assert(!phoneLocationValues(2,1,0,NAN,0,1));assert(!phoneLocationValues(2,1,0,0,INFINITY,1));
  assert(!phoneLocationValues(2,1,0,90.001,0,1));assert(!phoneLocationValues(2,1,0,0,-180.001,1));
  assert(!phoneLocationValues(2,1,0,0,0,0));assert(!phoneLocationValues(2,1,0,0,0,30.001));
  PhoneLocation loc;loc.seq=1;strcpy(loc.epoch,"00000000000000000000000000000001");loc.received=1000;loc.age=500;loc.active=true;
  assert(phoneLocationFresh(loc,3000));assert(!phoneLocationFresh(loc,3001));loc.active=false;assert(!phoneLocationFresh(loc,1000));
  loc.active=true;loc.received=UINT32_MAX-100;loc.age=100;assert(phoneLocationFresh(loc,100));assert(phoneLocationAge(loc,100)==301);
  loc.age=UINT32_MAX-2;loc.received=0;assert(phoneLocationAge(loc,100)==UINT32_MAX);
  puts("phone location: 18 sequence/age/accuracy/range/wrap/stop cases passed; no flight command");
}
