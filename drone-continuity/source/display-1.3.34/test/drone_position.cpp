#include "Truth.h"
#include <cassert>
#include <cstdio>
int main(){
  assert(verifiedDronePosition(3,true,true,0,0));assert(verifiedDronePosition(8,true,true,-90,180));
  assert(!verifiedDronePosition(2,true,true,45,-90));assert(!verifiedDronePosition(3,false,true,45,-90));
  assert(!verifiedDronePosition(3,true,false,45,-90));assert(!verifiedDronePosition(3,true,true,NAN,90));
  assert(!verifiedDronePosition(3,true,true,0,INFINITY));assert(!verifiedDronePosition(3,true,true,90.001,0));
  assert(!verifiedDronePosition(3,true,true,0,-180.001));assert(!verifiedDronePosition(9,true,true,0,0));
  puts("drone position: 10 fix/freshness/finite/range cases passed; no follow-target claim");
}
