#include <stdint.h>
#include <string>
#include <cstring>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <ArduinoJson.h>
static uint32_t tick=0;
uint32_t millis(){return tick;}
void delay(int n){tick+=n;}
#include "BufferedJsonReader.h"
#include "DisplayTelemetry.h"
#include "WidgetCache.h"
#include "DisplayOrientation.h"
struct Source {
 std::string data;size_t at=0,chunk=256;
 explicit Source(std::string s):data(s){}
 int read(uint8_t* b,size_t n){n=std::min(n,std::min(chunk,data.size()-at));memcpy(b,data.data()+at,n);at+=n;return int(n);}
 bool connected(){return at<data.size();}
};
struct Point {double x,y;};
Point convert(const uint16_t* c,double x,double y,int w,int h){
 Point p={(((c[4]&1)?y:x)-c[0])*w/c[1],(((c[4]&1)?x:y)-c[2])*h/c[3]};
 if(c[4]&2)p.x=w-p.x;
 if(c[4]&4)p.y=h-p.y;
 return p;
}
bool run(unsigned group,unsigned i){
 if(group==0){
  std::string body="{\"zero\":0,\"text\":\""+std::string(i%901,'a')+"\"}";
  Source s(body+"NEXT RESPONSE");s.chunk=1+i%513;BufferedJsonReader<Source> reader(s,body.size());DynamicJsonDocument d(2048);
  return !deserializeJson(d,reader)&&d["zero"].as<int>()==0&&strlen(d["text"])==i%901&&s.at==body.size()&&reader.read()==-1;
 }
 if(group==1){
  StaticJsonDocument<1536> d;d["schema"]=1;d["authority"]="advisory_only";d["generated_unix_ms"]=1792771400000ULL+i;
  auto m=d["h743"]["groundspeed_mps"];unsigned age=(i*17)%2400,transit=i%301;m["fresh"]=true;m["age_ms"]=age;
  unsigned v=i%5;if(v==0)m["value"]=0.;if(v==1)m["value"]=nullptr;if(v==2)m["value"]=true;if(v==3)m["value"]=201.;if(v==4)m["value"]=12.5;
  DisplayTelemetry t;bool ok=t.accept(d.as<JsonVariantConst>(),UINT32_MAX-200,transit);bool fresh=(v==0||v==4)&&age+transit<=2000;
  return ok&&t.fields[4].fresh==fresh&&(!fresh||t.fields[4].number==(v==0?0.:12.5))&&!metricFresh(t.fields[4],t.received,uint32_t(t.received+2001),2000);
 }
 if(group==2){
  StaticJsonDocument<2048> d;d["schema"]=1;d["authority"]="advisory_only";d["generated_unix_ms"]=1792771400000ULL+i;
  auto s=d["pi_service_health"];s["fresh"]=true;s["sample_succeeded"]=true;s["age_ms"]=i%1000;s["units"].add("example.service");
  DisplayTelemetry t;if(!t.accept(d.as<JsonVariantConst>(),1000)||!t.serviceCheckFresh||t.unitCount!=1)return false;
  if(i%3==0)d["schema"]=2;else if(i%3==1)d["authority"]="invalid"; // otherwise repeat producer stamp
  return !t.accept(d.as<JsonVariantConst>(),1001)&&!t.serviceCheckFresh&&t.unitCount==0;
 }
 if(group==3){
  WidgetCache c;int x=i%200,y=i%300;uint16_t color=i%65536;
  if(!c.changed(1,x,y,80,16,"0.0 m/s",color)||c.changed(1,x,y,80,16,"0.0 m/s",color))return false;
  if(!c.changed(1,x,y,80,16,"UNAVAILABLE",color)||c.changed(1,x,y,80,16,"UNAVAILABLE",color))return false;
  c.reset();return c.changed(1,x,y,80,16,"UNAVAILABLE",color);
 }
 uint16_t base[5]={250,3400,300,3300,uint16_t(i%8)},derived[5];unsigned r=(i/8)%4;orientedCalibration(base,r,derived);
 double x=400+(i*73)%2900,y=450+(i*91)%2800;Point old=convert(base,x,y,480,320),actual=convert(derived,x,y,(r&1)?480:320,(r&1)?320:480),expected=old;
 if(r==0)expected={320-old.y,old.x};
 if(r==2)expected={old.y,480-old.x};
 if(r==3)expected={480-old.x,320-old.y};
 return std::fabs(actual.x-expected.x)<0.00001&&std::fabs(actual.y-expected.y)<0.00001;
}
int main(){unsigned failures=0;const char* names[]={"fragmented_json_body_boundaries","zero_missing_range_expiry","invalid_packet_clears_service_health","incremental_screen_redraw","rotation_touch_geometry"};
 puts("{\"cases\":10000,\"groups\":[");
 for(unsigned g=0;g<5;++g){unsigned bad=0;for(unsigned i=0;i<2000;++i)if(!run(g,i))++bad;failures+=bad;printf("%s{\"name\":\"%s\",\"cases\":2000,\"failed\":%u}",g?",\n":"",names[g],bad);}
 printf("\n],\"failed\":%u,\"physical_screen_readback\":false,\"hardware_actions\":0}\n",failures);return failures?1:0;
}
