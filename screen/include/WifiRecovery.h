#pragma once
#include <stdint.h>

struct WifiRecovery {
  uint32_t invalidSince=0, lastRecovery=0;
  bool invalid=false, recovered=false;
  bool observe(uint32_t now, bool connected, int32_t rssi) {
    if(!connected || (rssi<0 && rssi>=-120)) {invalid=false;return false;}
    if(!invalid) {invalid=true;invalidSince=now;return false;}
    if(uint32_t(now-invalidSince)<3000) return false;
    if(recovered && uint32_t(now-lastRecovery)<15000) return false;
    recovered=true;lastRecovery=now;invalid=false;return true;
  }
};
