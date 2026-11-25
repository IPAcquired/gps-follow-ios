#include "Truth.h"
#include <assert.h>
#include <stdio.h>
int main() {
  const char* accepted[]={"192.0.2.10","192.168.0.132","172.16.0.1","172.31.255.254"};
  const char* rejected[]={"","8.8.8.8","127.0.0.1","172.15.0.1","172.32.0.1","192.168.00.1","10.1.2.999","10.1.2.3.evil","10.1.2","10.1.2.3:8090","10.1.2.3/","10.1..2"};
  for(auto p:accepted) assert(privateAddress(p));
  for(auto p:rejected) assert(!privateAddress(p));
  FlightView v; assert(!viewFresh(v,1));
  v.connected=true; v.received=10;
  assert(viewFresh(v,11)); assert(!viewFresh(v,3010));
  v.received=0xfffffff0; assert(viewFresh(v,0x10));
  assert(isnan(boundedNumber(NAN,0,80)));
  assert(isnan(boundedNumber(INFINITY,0,80)));
  assert(isnan(boundedNumber(-1,0,80)));
  assert(isnan(boundedNumber(81,0,80)));
  assert(boundedNumber(23.5,0,80)==23.5);
  assert(observationFresh(true,100,100,200));assert(!observationFresh(false,100,100,200));
  assert(!observationFresh(true,NAN,100,200));assert(!observationFresh(true,-1,100,200));
  assert(!observationFresh(true,3001,100,200));assert(!observationFresh(true,0,100,5100));
  puts("PASS: private endpoint validation, finite ranges, disconnected/stale/wraparound handling");
}
