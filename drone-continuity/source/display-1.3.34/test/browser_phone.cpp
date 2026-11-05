#include "DisplayTelemetry.h"
#include <cassert>
#include <cstdio>
int main(){
  DynamicJsonDocument doc(4096);deserializeJson(doc,R"({"schema":1,"authority":"advisory_only","generated_unix_ms":1792771200000,"follow_location":{"status":"fresh","authority":"advisory_only","position_is_drone_gps":false,"transport":"phone_browser_wifi","age_ms":100,"accuracy_m":8,"lat":42,"lon":-90}})");
  DisplayTelemetry data;auto next=[&](uint32_t transit){doc["generated_unix_ms"]=doc["generated_unix_ms"].as<uint64_t>()+1;return data.accept(doc.as<JsonVariantConst>(),1000,transit);};
  assert(next(200)&&data.phoneFresh&&data.phoneBrowser&&data.phoneAge==300&&data.phoneAccuracy==8);
  assert(next(2900)&&!data.phoneFresh);
  doc["follow_location"]["position_is_drone_gps"]=true;assert(next(0)&&!data.phoneFresh);
  doc["follow_location"]["position_is_drone_gps"]=false;doc["follow_location"]["lat"]=true;assert(next(0)&&!data.phoneFresh);
  doc["follow_location"]["lat"]=42;doc["follow_location"]["accuracy_m"]=31;assert(next(0)&&!data.phoneFresh);
  doc["follow_location"]["accuracy_m"]=8;doc["follow_location"]["status"]="stopped";assert(next(0)&&!data.phoneFresh);
  doc["follow_location"]["status"]="fresh";assert(next(0)&&data.phoneFresh);data.invalidate();assert(!data.phoneFresh);
  puts("browser phone telemetry: source distinction, no drone substitution, age, types, accuracy, stop and invalidation passed");
}
