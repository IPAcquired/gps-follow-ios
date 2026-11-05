#pragma once
#include <stdint.h>
#include <string.h>
inline bool strongHotspotPassword(const char* p) {
  if(!p)return false;
  size_t n=strlen(p);if(n<12||n>63)return false;
  bool seen[95]={};unsigned distinct=0;
  for(size_t i=0;i<n;++i){unsigned c=static_cast<unsigned char>(p[i]);if(c<32||c>126)return false;if(!seen[c-32]){seen[c-32]=true;++distinct;}}
  return distinct>=5;
}
inline bool pairingPin(const char* p,uint32_t& out) {
  if(!p||strlen(p)!=6)return false;
  out=0;bool same=true;
  for(int i=0;i<6;++i){if(p[i]<'0'||p[i]>'9')return false;out=out*10+unsigned(p[i]-'0');if(p[i]!=p[0])same=false;}
  return !same&&strcmp(p,"123456")&&strcmp(p,"654321");
}
inline bool pairingWindow(uint32_t now,uint32_t began,bool open) {return open&&uint32_t(now-began)<60000;}
