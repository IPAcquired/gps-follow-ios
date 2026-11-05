#pragma once
#include <stdint.h>
#include <stddef.h>
// Fixed storage: no framebuffer and no persistent heap allocations competing
// with TLS. Cache only drawing decisions, never telemetry or freshness state.
struct WidgetCache {
  struct Entry {uint64_t hash=0; int16_t x=0,y=0,w=0,h=0;uint8_t kind=0;};
  Entry entries[96]; size_t next=0;
  void reset(){for(auto& e:entries)e.kind=0;next=0;}
  void resetKind(uint8_t kind){for(auto& e:entries)if(e.kind==kind)e.kind=0;}
  bool changed(uint8_t kind,int x,int y,int w,int h,const char* value,uint16_t color){
    uint64_t hash=14695981039346656037ULL;
    for(const unsigned char* c=(const unsigned char*)value;*c;++c){hash^=*c;hash*=1099511628211ULL;}
    hash^=color;hash*=1099511628211ULL;
    Entry* empty=nullptr;
    for(auto& e:entries){
      if(!e.kind&&!empty)empty=&e;
      if(e.kind==kind&&e.x==x&&e.y==y&&e.w==w&&e.h==h){bool update=e.hash!=hash;e.hash=hash;return update;}
    }
    Entry& e=empty?*empty:entries[next++%96];
    e.hash=hash;e.x=x;e.y=y;e.w=w;e.h=h;e.kind=kind;return true;
  }
};
