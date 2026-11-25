#include "DisplayTelemetry.h"
#include <cassert>
#include <string>

size_t slotCount(JsonVariantConst value) {
  size_t count=0;
  for(auto item:value.as<JsonObjectConst>())count+=1+slotCount(item.value());
  for(auto item:value.as<JsonArrayConst>())count+=1+slotCount(item);
  return count;
}
int main(){
  StaticJsonDocument<JSON_OBJECT_SIZE(80)> filter;
  displayTelemetryFilter(filter);assert(!filter.overflowed()&&slotCount(filter.as<JsonVariantConst>())==80);
  DynamicJsonDocument producer(131072),got(65536);
  producer["schema"]=1;producer["authority"]="advisory_only";producer["generated_unix_ms"]=uint64_t(1795658400000ULL);
  for(auto& item:METRICS){
    auto metric=producer[item.pi?"pi":"h743"][item.key];metric["value"]=1;metric["fresh"]=true;
    metric["age_ms"]=100;metric["source"]=std::string("field.")+item.key;metric["reason"]="not retained";
  }
  producer["h743"]["connected"]["value"]=true;producer["h743"]["connected"]["source"]="HEARTBEAT";
  auto profile=producer["controller_profile"];profile["configured_model"]="CORVON743V2";profile["configured_board_id"]=1229;profile["source_state"]="matching";profile["presence"]="heartbeat";
  for(const char* name:{"rplidar","matrix_lidar","camera"}){
    auto sensor=producer["sensor_health"][name];sensor["fresh"]=true;sensor["device_node_present"]=true;sensor["data_age_ms"]=20;sensor["status"]="fresh_data";
  }
  for(unsigned i=0;i<18;i++){
    auto rc=producer["rc_channels"];rc["values"][i]=1500;rc["fresh"][i]=true;rc["age_ms"][i]=50;
  }
  for(unsigned i=0;i<8;i++){
    auto range=producer["rangefinders"][i];range["id"]=i;
    for(const char* k:{"distance_cm","orientation"}){auto m=range[k];m["value"]=20;m["fresh"]=true;m["age_ms"]=100;}
    producer["pi_service_health"]["units"][i]=std::string(63,char('a'+i));
  }
  for(unsigned i=0;i<6;i++){
    auto msg=producer["messages"][i];msg["text"]=std::string(120,char('A'+i));msg["time_utc"]="2000-01-01T00:00:00Z";msg["severity"]=2;msg["age_ms"]=400;
  }
  for(unsigned i=0;i<10;i++){auto f=producer["faults"][i];f["component"]="pi";f["text"]=std::string(120,char('k'+i));f["age_ms"]=50;}
  std::string serial;serializeJson(producer,serial);assert(!producer.overflowed());
  assert(!deserializeJson(got,serial,DeserializationOption::Filter(filter)));
  const size_t slots=slotCount(got.as<JsonVariantConst>());
  const size_t estimate=got.memoryUsage()-slots*(JSON_OBJECT_SIZE(1)-16);
  assert(estimate<12288);
  assert(got["h743"]["connected"]["source"]=="HEARTBEAT"&&got["h743"]["groundspeed_mps"]["source"].isNull());
  assert(got["h743"]["groundspeed_mps"]["fresh"]==true&&got["pi"]["memory_total_bytes"]["age_ms"]==100);
  assert(got["h743"]["groundspeed_mps"]["reason"].isNull()&&got["rangefinders"].size()==8);
  DisplayTelemetry view;
  const uint64_t now=1795658400000ULL;
  assert(view.accept(got.as<JsonVariantConst>(),0,0,now)&&view.sourceHeartbeat);
  assert(!view.accept(got.as<JsonVariantConst>(),1,0,now)&&!strcmp(view.rejection,"duplicate_or_reversed"));
  got["generated_unix_ms"]=now+1;
  assert(!view.accept(got.as<JsonVariantConst>(),10,0,now+10000)&&!strcmp(view.rejection,"clock_window"));
  printf("PASS compact filter uses 80 ESP32 slots (1280 bytes); dense filtered document estimate %zu bytes in 12288-byte pool.\n",estimate);
}
