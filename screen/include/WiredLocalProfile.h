#pragma once
#include <cstdio>
#include <cstring>
#include <cstdint>

struct WiredLocalProfile {
  char dns[64]{},origin[88]{},home[33]{};
  static bool dnsValid(const char* p){
    size_t n=p?strlen(p):0;if(n<7||n>63||strcmp(p+n-6,".local"))return false;
    bool first=true;
    for(size_t i=0;i<n;i++){char c=p[i];
      if(c=='.'){if(first||p[i-1]=='-')return false;first=true;continue;}
      if(!((c>='a'&&c<='z')||(c>='0'&&c<='9')||(!first&&c=='-')))return false;
      first=false;
    }
    return !first;
  }
  static bool valid(const char* dns,const char* origin,const char* home){
    if(!dnsValid(dns)||!origin||!home)return false;
    size_t n=strlen(home);if(!n||n>32)return false;
    for(size_t i=0;i<n;i++)if(uint8_t(home[i])<32||uint8_t(home[i])==127)return false;
    char expected[88];snprintf(expected,sizeof expected,"https://%s:8446",dns);return !strcmp(expected,origin);
  }
  bool set(const char* host,const char* site,const char* ssid){
    if(!valid(host,site,ssid))return false;
    strcpy(dns,host);strcpy(origin,site);strcpy(home,ssid);return true;
  }
  bool valid()const{
    return memchr(dns,0,sizeof dns)&&memchr(origin,0,sizeof origin)&&memchr(home,0,sizeof home)&&valid(dns,origin,home);
  }
};
extern WiredLocalProfile displayLocalProfile;
bool localProfileReady();
