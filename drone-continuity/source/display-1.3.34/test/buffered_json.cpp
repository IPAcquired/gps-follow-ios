#include <stdint.h>
#include <string>
#include <cstring>
#include <cassert>
#include <algorithm>
#include <ArduinoJson.h>
static uint32_t tick=0;
uint32_t millis(){return tick;}
void delay(int n){tick+=n;}
#include "BufferedJsonReader.h"
struct Source {
 std::string data;size_t at=0,chunk=256,calls=0;bool stall=false;
 explicit Source(std::string s):data(s){}
 int read(uint8_t* b,size_t n){++calls;if(stall)return 0;n=std::min(n,std::min(chunk,data.size()-at));memcpy(b,data.data()+at,n);at+=n;return int(n);}
 bool connected(){return stall||at<data.size();}
};
int main(){
 for(size_t chunk=1;chunk<=300;++chunk){
  std::string body="{\"zero\":0,\"text\":\""+std::string(900,'a')+"\"}";
  Source source(body+"DO NOT READ NEXT RESPONSE");source.chunk=chunk;
  BufferedJsonReader<Source> reader(source,body.size());DynamicJsonDocument doc(2048);
  assert(!deserializeJson(doc,reader));assert(doc["zero"].as<int>()==0);assert(strlen(doc["text"])==900);
  assert(source.at==body.size());assert(reader.read()==-1);
  if(chunk>=256)assert(source.calls<=4);
 }
 Source shortBody("{\"zero\":");BufferedJsonReader<Source> truncated(shortBody,100);DynamicJsonDocument doc(1024);assert(deserializeJson(doc,truncated));
 Source stalled("");stalled.stall=true;BufferedJsonReader<Source> waiting(stalled,10);uint32_t before=tick;assert(waiting.read()==-1);assert(tick-before==1500);
 tick=UINT32_MAX-200;BufferedJsonReader<Source> wrapped(stalled,10);before=tick;assert(wrapped.read()==-1);assert(uint32_t(tick-before)==1500);
}
