#pragma once
#include <stddef.h>
#include <stdint.h>
inline bool decodeDesktopRow(const uint8_t* source,size_t length,uint16_t* pixels,size_t width){
 size_t i=0,out=0;
 while(i<length){
  uint8_t control=source[i++];size_t count=(control&127)+1;
  if(count>width-out)return false;
  if(control&128){
   if(length-i<2)return false;
   uint16_t value=source[i]|uint16_t(source[i+1])<<8;i+=2;
   while(count--)pixels[out++]=value;
  }else{
   if(length-i<count*2)return false;
   while(count--){pixels[out++]=source[i]|uint16_t(source[i+1])<<8;i+=2;}
  }
 }
 return out==width;
}
