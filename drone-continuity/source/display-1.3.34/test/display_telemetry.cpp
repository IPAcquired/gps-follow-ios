#include "DisplayTelemetry.h"
#include <cassert>
#include <fstream>
#include <sstream>
#include <cstdio>
size_t slots(JsonVariantConst value){size_t n=0;if(value.is<JsonObjectConst>()){for(auto pair:value.as<JsonObjectConst>()){++n;n+=slots(pair.value());}}else if(value.is<JsonArrayConst>()){for(auto item:value.as<JsonArrayConst>()){++n;n+=slots(item);}}return n;}
int main(int argc,char** argv){
  DisplayMetric heartbeat;heartbeat.fresh=true;heartbeat.number=0;heartbeat.age=1800;
  assert(metricFresh(heartbeat,1000,1600,METRICS[1].ttl));
  assert(!metricFresh(heartbeat,1000,2201,METRICS[1].ttl));
  assert(!metricFresh(heartbeat,1000,1600,2000)); // owner evidence remains stricter
  assert(argc==2);std::ifstream file(argv[1]);std::stringstream stream;stream<<file.rdbuf();std::string body=stream.str();assert(body.size()>10000);
  // Host JSON slots use 64-bit pointers, so the filter needs twice ESP32's
  // slot storage. Exact slot/string accounting below verifies target capacity.
  DynamicJsonDocument filter(8192),doc(24576);displayTelemetryFilter(filter);assert(!filter.overflowed());
  auto error=deserializeJson(doc,body,DeserializationOption::Filter(filter));
  if(error){printf("filtered JSON failure: %s / capacity%zu\n",error.c_str(),doc.capacity());return 1;}
  size_t nodeBytes=JSON_OBJECT_SIZE(1),targetDoc=doc.memoryUsage()-slots(doc.as<JsonVariantConst>())*(nodeBytes-16),targetFilter=filter.memoryUsage()-slots(filter.as<JsonVariantConst>())*(nodeBytes-16);
  assert(targetDoc<=12288&&targetFilter<=4096);
  printf("worst fixture wire=%zu host memory=%zu; exact ESP32 slot/string budget document=%zu/12288 filter=%zu/4096\n",body.size(),doc.memoryUsage(),targetDoc,targetFilter);
  doc["generated_unix_ms"]=1792771200000ULL; // Normalize only the fixture's toy epoch.
  DisplayTelemetry data;assert(data.accept(doc.as<JsonVariantConst>(),1000));assert(data.rangeCount==8);
  assert(!data.accept(doc.as<JsonVariantConst>(),1100)); // frozen producer timestamp
  assert(!data.fields[0].fresh); // failure immediately clears old measurements
  StaticJsonDocument<1024> good;deserializeJson(good,R"({"schema":1,"authority":"advisory_only","generated_unix_ms":1792771200000,"h743":{"connected":{"value":true,"fresh":true,"age_ms":0},"groundspeed_mps":{"value":2,"fresh":true,"age_ms":200}},"pi":{}})");
  DisplayTelemetry current;assert(current.accept(good.as<JsonVariantConst>(),2000,100));assert(metricFresh(current.fields[4],current.received,2700,1000));assert(!metricFresh(current.fields[4],current.received,2701,1000));
  good["generated_unix_ms"]=1792771200001ULL;good["h743"]["connected"]["value"]=1;assert(current.accept(good.as<JsonVariantConst>(),3000));assert(!current.fields[0].fresh);
  good["generated_unix_ms"]=1792771200002ULL;good["h743"]["connected"]["value"]=true;good["h743"]["groundspeed_mps"]["fresh"]="true";assert(current.accept(good.as<JsonVariantConst>(),4000));assert(!current.fields[4].fresh);
  good["generated_unix_ms"]=1792771200003ULL;good["h743"]["groundspeed_mps"]["fresh"]=true;assert(current.accept(good.as<JsonVariantConst>(),5000,1801));assert(!current.fields[4].fresh);
  good["generated_unix_ms"]=1792771200004ULL;assert(!current.accept(good.as<JsonVariantConst>(),6000,0,1792771300000ULL));
  assert(METRIC_COUNT==47);
  assert(strcmp(METRICS[40].key,"board_voltage_v")==0);
  for(int i=40;i<47;++i){
    DynamicJsonDocument power(2048);power["schema"]=1;power["authority"]="advisory_only";power["generated_unix_ms"]=1792771200010ULL+i;
    auto metric=power[METRICS[i].pi?"pi":"h743"][METRICS[i].key];metric["value"]=5;metric["fresh"]=true;metric["age_ms"]=100;
    DisplayTelemetry reading;assert(reading.accept(power.as<JsonVariantConst>(),1000));assert(reading.fields[i].fresh);assert(reading.fields[i].number==5);
    assert(metricFresh(reading.fields[i],1000,5900,5000));assert(!metricFresh(reading.fields[i],1000,5901,5000));
    power["generated_unix_ms"]=1792771200100ULL+i;metric["value"]=true;assert(reading.accept(power.as<JsonVariantConst>(),1000));assert(!reading.fields[i].fresh);
  }
  // 10,000 independent source-age/value cases: zero is a valid value,
  // null/false freshness/nonfinite and expiry never become a displayed zero.
  for(unsigned i=0;i<10000;++i){
    DynamicJsonDocument sample(1024);sample["schema"]=1;sample["authority"]="advisory_only";sample["generated_unix_ms"]=1792771400000ULL+i;
    auto m=sample["h743"]["groundspeed_mps"];unsigned age=i%2300;m["age_ms"]=age;m["fresh"]=i%3!=0;
    if(i%5)m["value"]=0.0;else m["value"]=nullptr;
    DisplayTelemetry read;assert(read.accept(sample.as<JsonVariantConst>(),10000,100));
    bool expected=i%3!=0&&i%5!=0&&age+100<=METRICS[4].ttl;
    assert(read.fields[4].fresh==expected);
    if(expected){assert(read.fields[4].number==0);assert(strcmp(read.fields[4].text,"0.0 m/s")==0);assert(!metricFresh(read.fields[4],10000,12001,METRICS[4].ttl));}
  }
  puts("compact telemetry: worst JSON, frozen producer, strict types, source+transport age, stale expiry, seven power fields and old-response rejection passed");
}
