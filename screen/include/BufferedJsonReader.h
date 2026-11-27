#pragma once
#include <stddef.h>
#include <stdint.h>
// ArduinoJson's direct Stream reader invokes TLS once per byte. Fetch bounded
// blocks instead, never consuming bytes beyond this HTTP response body.
template<class Source> class BufferedJsonReader {
 Source& source;size_t remaining,position=0,count=0;uint8_t bytes[256];
 public:
 BufferedJsonReader(Source& input,size_t length):source(input),remaining(length){}
 int read(){
  if(position<count)return bytes[position++];
  if(!remaining)return -1;
  uint32_t began=millis();
  while(uint32_t(millis()-began)<1500){
   int n=source.read(bytes,remaining<sizeof(bytes)?remaining:sizeof(bytes));
   if(n>0){count=size_t(n);position=1;remaining-=count;return bytes[0];}
   if(!source.connected())return -1;
   delay(1);
  }
  return -1;
 }
 size_t readBytes(char* output,size_t length){size_t n=0;while(n<length){int c=read();if(c<0)break;output[n++]=char(c);}return n;}
};
