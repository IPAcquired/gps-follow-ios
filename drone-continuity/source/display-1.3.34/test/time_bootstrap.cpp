#include "TimeBootstrapPolicy.h"
#include <cassert>
#include <cstdio>
#include <cstring>
int main(){
  assert(bootstrapId("display_5460-1"));assert(!bootstrapId(""));assert(!bootstrapId("bad\nid"));assert(!bootstrapId("a/b"));
  assert(bootstrapId("12345678901234567890123456789012"));assert(!bootstrapId("123456789012345678901234567890123"));
  uint8_t decoded[32]={};const char* input="000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
  assert(decodeHex256(input,decoded));for(int i=0;i<32;++i)assert(decoded[i]==i);
  char malformed[66];strcpy(malformed,input);malformed[63]='x';assert(!decodeHex256(malformed,decoded));
  strcpy(malformed,input);malformed[64]='0';malformed[65]=0;assert(!decodeHex256(malformed,decoded));
  assert(!decodeHex256("00",decoded));assert(!bootstrapEpoch(0));assert(!bootstrapEpoch(1792022399));assert(bootstrapEpoch(1792022400));assert(bootstrapEpoch(4102444799));assert(!bootstrapEpoch(4102444800));
  uint8_t first[32]={},second[32]={};assert(constantTime256(first,second));
  for(int i=0;i<32;++i){second[i]=1;assert(!constantTime256(first,second));second[i]=0;}
  puts("time bootstrap: identifier/hex/epoch/constant-time comparison cases passed");
}
