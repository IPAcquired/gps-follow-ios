#include "MaintenanceGate.h"
#include <cassert>
int main(){
 for(int mask=0;mask<512;++mask){MaintenanceEvidence e;
 e.heartbeatFresh=mask&1;e.armedKnown=mask&2;e.armed=mask&4;e.groundFresh=mask&8;e.onGround=mask&16;
 e.tlsFresh=mask&32;e.ownerAuthenticated=mask&64;e.directPiAp=mask&128;e.controllerAbsent=mask&256;e.wifiDbm=-60;
 bool expected=(bool(mask&256)||((mask&1)&&(mask&2)&&!(mask&4)))&&(!(mask&8)||(mask&16))&&(mask&32)&&(mask&64)&&(mask&128);
 assert(maintenanceConditions(e)==expected);
 }
 MaintenanceEvidence e;e.tlsFresh=e.ownerAuthenticated=e.directPiAp=e.controllerAbsent=true;e.wifiDbm=-80;assert(maintenanceConditions(e));
 e.wifiDbm=0;assert(!maintenanceConditions(e));
}
