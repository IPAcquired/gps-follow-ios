#pragma once
#include <stdint.h>
// Advisory data-link quality, not battery charge or flight readiness.
enum class BarQuality:uint8_t {Good,Medium,Weak,Poor,Unavailable};
inline BarQuality worseBar(BarQuality a,BarQuality b){return uint8_t(a)>uint8_t(b)?a:b;}
inline BarQuality signalBar(bool connected,int dbm){
  if(!connected||dbm>=0||dbm< -127)return BarQuality::Unavailable;
  return dbm>=-60?BarQuality::Good:dbm>=-70?BarQuality::Medium:dbm>=-80?BarQuality::Weak:BarQuality::Poor;
}
inline BarQuality freshnessBar(bool valid,uint64_t age,uint32_t ttl){
  if(!valid||!ttl||age>=ttl)return BarQuality::Unavailable;
  return age*100<ttl*50ULL?BarQuality::Good:age*100<ttl*70ULL?BarQuality::Medium:age*100<ttl*90ULL?BarQuality::Weak:BarQuality::Poor;
}
inline bool barLit(BarQuality quality,uint32_t now){return quality!=BarQuality::Unavailable||(now/500)%2==0;}
inline uint16_t barRgb565(BarQuality quality,uint32_t now,uint16_t panel){
  if(!barLit(quality,now))return panel;
  return quality==BarQuality::Good?0x07E0:quality==BarQuality::Medium?0xFFE0:quality==BarQuality::Weak?0xFD20:0xF800;
}
