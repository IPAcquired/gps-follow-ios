#pragma once
#include <stdint.h>
#include <stdio.h>

enum class FieldHealth:uint8_t {Unknown,Missing,Stale,Fresh};
struct FieldSensor {FieldHealth health=FieldHealth::Unknown;uint32_t age=UINT32_MAX;};
struct FieldSample {
  uint64_t publication=0;
  uint32_t uptime=0,sequence=0,heartbeatAge=UINT32_MAX;
  int32_t batteryMv=-1,groundspeedMmps=-1;
  int8_t connected=-1,armed=-1;
  FieldSensor sensors[3];
};
inline uint32_t fieldAge(uint32_t reportAge,uint32_t transferMs){
  return reportAge<UINT32_MAX-transferMs?reportAge+transferMs:UINT32_MAX;
}
inline int formatFieldSample(const FieldSample& sample,char* output,size_t limit){
  const auto boolean=[](int state){return state<0?"null":state?"true":"false";};
  char voltage[18]{},speed[18]{};
  const auto milli=[](char (&out)[18],int32_t value){
    if(value<0)snprintf(out,sizeof out,"null");
    else snprintf(out,sizeof out,"%ld.%03ld",static_cast<long>(value/1000),static_cast<long>(value%1000));
  };
  milli(voltage,sample.batteryMv);milli(speed,sample.groundspeedMmps);
  char ages[4][12]{};
  for(unsigned i=0;i<4;++i){
    uint32_t v=i==3?sample.heartbeatAge:sample.sensors[i].age;
    if(v==UINT32_MAX)snprintf(ages[i],12,"null");else snprintf(ages[i],12,"%lu",static_cast<unsigned long>(v));
  }
  const auto health=[](FieldHealth state){
    switch(state){case FieldHealth::Fresh:return "\"fresh\"";case FieldHealth::Missing:return "\"missing\"";
      case FieldHealth::Stale:return "\"stale\"";default:return "null";}
  };
  return snprintf(output,limit,
    "{\"schema\":2,\"seq\":%lu,\"uptime_ms\":%lu,\"publication_unix_ms\":%llu,"
    "\"corvon\":{\"connected\":%s,\"heartbeat_age_ms\":%s,\"armed\":%s,\"battery_voltage_v\":%s,\"groundspeed_mps\":%s},"
    "\"c1\":{\"health\":%s,\"age_ms\":%s},\"matrix\":{\"health\":%s,\"age_ms\":%s},"
    "\"camera\":{\"health\":%s,\"age_ms\":%s}}\n",
    static_cast<unsigned long>(sample.sequence),static_cast<unsigned long>(sample.uptime),
    static_cast<unsigned long long>(sample.publication),boolean(sample.connected),ages[3],boolean(sample.armed),voltage,speed,
    health(sample.sensors[0].health),ages[0],health(sample.sensors[1].health),ages[1],health(sample.sensors[2].health),ages[2]);
}
