#include "OwnerLease.h"
#include <cassert>
int main(){
 for(uint32_t t=0;t<300000;t+=31){assert(ownerLeaseHeld(true,7,7,1000+t,1000));assert(ownerLeaseHeld(true,7,7,1000+t,1000));}
 assert(ownerLeaseHeld(true,7,7,300999,1000));assert(!ownerLeaseHeld(true,7,7,301000,1000));
 assert(!ownerLeaseHeld(true,7,8,2000,1000));
 assert(ownerLeaseHeld(true,7,7,2000,1000)&&!ownerLeaseValid(true,7,7,2000,1000,false,false,0,false,false));

 assert(ownerLeaseValid(true,1,1,1000,500,true,true,900,false,false));
 for(int mask=0;mask<256;++mask){bool result=ownerLeaseValid(mask&1,1,(mask&2)?1:2,1000,(mask&4)?500:1001,mask&8,mask&16,(mask&32)?900:0,!(mask&64),!(mask&128));assert(result==(mask==255));}
 assert(ownerLeaseValid(true,1,1,10000,1,true,true,1,false,false));
 assert(!ownerLeaseValid(true,1,1,10002,1,true,true,1,false,false));
 assert(!ownerLeaseValid(true,1,1,300001,1,true,true,300000,false,false));
}
