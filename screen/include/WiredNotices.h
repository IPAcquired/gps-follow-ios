#pragma once
#include <stdint.h>
#include <string.h>

namespace wirednotice {
enum Level : uint8_t { None, Audio, Warning, Error, Critical, Alert, Emergency };
inline Level levelOf(const char* name) {
  if(!strcmp(name,"warning"))return Warning;
  if(!strcmp(name,"error"))return Error;
  if(!strcmp(name,"critical"))return Critical;
  if(!strcmp(name,"alert"))return Alert;
  if(!strcmp(name,"emergency"))return Emergency;
  return None;
}
inline const char* label(Level lv){
  const char* const labels[]={"","AUDIO","WARNING","ERROR","CRITICAL","ALERT","EMERGENCY"};
  return labels[lv];
}
struct Notice {
  Level level=None;
  char text[181]{};
};
// One incident per severity and full message, with distinct source event times.
// Polling the same snapshot is not a new observation. Periodic retransmission
// with a fresh source timestamp keeps the indication without repeating takeover.
class Tracker {
 public:
  static constexpr uint32_t HardMs=10000, QuietMs=95000, WarningMs=12000;
  void observe(Level level,double sourceTime,const char* text,uint32_t now){
    if(level<Warning || !text || !text[0] || strlen(text)>180)return;
    Entry* entry=nullptr;
    Entry* candidate=nullptr;
    for(auto& slot:slots_){
      if(slot.notice.level==level && !strcmp(slot.notice.text,text)){entry=&slot;break;}
      if(slot.notice.level==None){candidate=&slot;continue;}
      // Keep active critical incidents when a large volume of warnings arrives.
      if(level==Warning && slot.notice.level>Warning && now-slot.last<QuietMs)continue;
      if(!candidate || (candidate->notice.level!=None && now-slot.last>now-candidate->last))
        candidate=&slot;
    }
    bool incident=true;
    if(entry){
      if(sourceTime<=entry->stamp)return;
      incident=uint32_t(now-entry->last)>=QuietMs || sourceTime-entry->stamp>=QuietMs/1000.0;
    }else{
      if(!candidate)return;
      entry=candidate;
      entry->notice.level=level;
      strcpy(entry->notice.text,text);
    }
    entry->stamp=sourceTime;entry->last=now;
    if(incident && level>=Error){
      if(!hard(now)||level>=priority_.level)priority_=entry->notice;
      hardAt_=now;hasPriority_=true;
    }
  }
  bool hard(uint32_t now)const{return hasPriority_ && uint32_t(now-hardAt_)<HardMs;}
  Notice current(uint32_t now)const{
    if(hard(now))return priority_;
    const Entry* top=nullptr;
    for(const auto& slot:slots_){
      Level level=slot.notice.level;
      if(level==None||uint32_t(now-slot.last)>=(level==Warning?WarningMs:QuietMs))continue;
      if(!top||level>top->notice.level||(level==top->notice.level&&now-slot.last<now-top->last))top=&slot;
    }
    return top?top->notice:Notice{};
  }
 private:
  struct Entry{Notice notice;double stamp=0;uint32_t last=0;};
  Entry slots_[16]{};
  Notice priority_;
  bool hasPriority_=false;
  uint32_t hardAt_=0;
};
}
