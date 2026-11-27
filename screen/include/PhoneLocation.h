#pragma once
#include <stdint.h>
#include <math.h>
struct PhoneLocation {
  uint32_t revision=0,seq=0,received=0,age=0;
  double latitude=NAN,longitude=NAN;
  float accuracy=NAN;
  bool active=false;
  char epoch[33]={};
};
inline bool phoneLocationValues(uint32_t seq,uint32_t previous,uint32_t age,double latitude,double longitude,double accuracy){
  return seq>previous&&seq>0&&seq<UINT32_MAX&&age<=1000&&isfinite(latitude)&&isfinite(longitude)&&latitude>=-90&&latitude<=90&&longitude>=-180&&longitude<=180&&isfinite(accuracy)&&accuracy>0&&accuracy<=30;
}
inline uint32_t phoneLocationAge(const PhoneLocation& value,uint32_t now){
  uint32_t elapsed=uint32_t(now-value.received);return elapsed>UINT32_MAX-value.age?UINT32_MAX:value.age+elapsed;
}
inline bool phoneLocationFresh(const PhoneLocation& value,uint32_t now){return value.active&&value.seq>0&&value.epoch[0]&&phoneLocationAge(value,now)<=2500;}
