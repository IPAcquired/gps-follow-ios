#pragma once
#include <stdint.h>
#include <stddef.h>
inline bool bootstrapId(const char* id){
  if(!id)return false;
  size_t n=0;
  for(;id[n];++n)if(n>=32||!((id[n]>='a'&&id[n]<='z')||(id[n]>='A'&&id[n]<='Z')||(id[n]>='0'&&id[n]<='9')||id[n]=='_'||id[n]=='-'))return false;
  return n>0;
}
inline int hexNibble(char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
inline bool decodeHex256(const char* input,uint8_t* output){
  if(!input)return false;
  for(size_t i=0;i<64;++i)if(!input[i]||hexNibble(input[i])<0)return false;
  if(input[64])return false;
  for(size_t i=0;i<32;++i)output[i]=(hexNibble(input[i*2])<<4)|hexNibble(input[i*2+1]);
  return true;
}
inline bool bootstrapEpoch(uint32_t epoch){return epoch>=1792022400UL&&epoch<4102444800UL;}
inline bool constantTime256(const uint8_t* a,const uint8_t* b){uint8_t diff=0;for(int i=0;i<32;++i)diff|=a[i]^b[i];return diff==0;}
