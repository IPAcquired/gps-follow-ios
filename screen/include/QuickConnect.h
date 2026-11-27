#pragma once
#include <stdint.h>
#include "WiredLocalProfile.h"
#include <string.h>
struct DashboardCode {
  char url[128]={}; uint32_t received=0,ttl=0,revision=0;
  bool fresh(uint32_t now) const {return url[0]&&ttl>0&&uint32_t(now-received)<ttl;}
  bool set(const char* value,uint32_t seconds,uint32_t now){
    if(!localProfileReady())return false;
    char prefix[96];int count=snprintf(prefix,sizeof prefix,"%s/#join=",displayLocalProfile.origin);
    if(count<1||size_t(count)>=sizeof prefix||size_t(count)+43>=sizeof url)return false;
    const unsigned n=strlen(prefix);
    if(!value||strlen(value)!=n+43||strncmp(value,prefix,n)||seconds<1||seconds>120)return false;
    for(unsigned i=n;i<n+43;++i){char c=value[i];if(!((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'||c=='-'))return false;}
    strcpy(url,value);received=now;ttl=seconds*1000;revision++;return true;
  }
  void clear(){memset(url,0,sizeof(url));ttl=0;revision++;}
};
