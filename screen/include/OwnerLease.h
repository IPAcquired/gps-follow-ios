#pragma once
#include <stdint.h>
constexpr uint32_t OWNER_LEASE_MS=300000;
inline bool ownerLeaseHeld(bool confirmed,uint32_t confirmedEpoch,uint32_t epoch,uint32_t now,uint32_t confirmedAt){
 return confirmed&&confirmedEpoch==epoch&&uint32_t(now-confirmedAt)<OWNER_LEASE_MS;
}
inline bool ownerLeaseValid(bool confirmed,uint32_t confirmedEpoch,uint32_t epoch,uint32_t now,uint32_t confirmedAt,bool authenticated,bool wifi,uint32_t tlsAt,bool armed,bool airborne){
 return ownerLeaseHeld(confirmed,confirmedEpoch,epoch,now,confirmedAt)&&authenticated&&wifi&&tlsAt&&uint32_t(now-tlsAt)<=10000&&!armed&&!airborne;
}
