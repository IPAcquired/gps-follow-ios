#pragma once
#include <stdint.h>
struct IPAddress { uint32_t value; explicit IPAddress(uint32_t v=0):value(v){} };
class WiFiClientSecure {
 protected: int32_t _timeout=0;
 public:
  int handshakes=0;const char* verifiedName=nullptr;const char* certificate=nullptr;
  virtual ~WiFiClientSecure()=default;
  virtual int connect(const char*,uint16_t){return 0;}
  virtual int connect(const char*,uint16_t,int32_t){return 0;}
  int connect(IPAddress,uint16_t,const char* name,const char* ca,const char*,const char*){++handshakes;verifiedName=name;certificate=ca;return 1;}
};
