#include "DisplayTelemetry.h"
#include "MaintenanceGate.h"
#include <cassert>
using namespace ArduinoJson;
int main(){
  DynamicJsonDocument doc(8192),filter(16384);
  displayTelemetryFilter(filter);
  assert(filter["controller_profile"]["source_state"]==true&&filter["h743"]["connected"]["source"]==true);
  doc["schema"]=1;doc["authority"]="advisory_only";uint64_t stamp=1795658400000ULL;
  auto link=doc["h743"]["connected"];link["source"]="HEARTBEAT";link["fresh"]=true;link["value"]=true;link["age_ms"]=0;
  auto speed=doc["h743"]["groundspeed_mps"];speed["value"]=0;speed["fresh"]=true;speed["age_ms"]=0;
  auto node=doc["sensor_health"]["rplidar"];node["status"]="fresh_data";node["fresh"]=true;node["device_node_present"]=true;node["data_age_ms"]=0;
  DisplayTelemetry d;
  auto receive=[&](unsigned transport=0){doc["generated_unix_ms"]=++stamp;assert(d.accept(doc.as<JsonVariantConst>(),10000,transport,stamp));};
  receive();assert(d.sourceHeartbeat&&!d.profileProvided&&d.fields[0].fresh&&d.sensorFresh[0]&&!d.sensorFresh[1]);
  auto profile=doc["controller_profile"];profile["configured_board_id"]=1229;profile["configured_model"]="CORVON743V2";profile["source_state"]="matching";profile["presence"]="heartbeat";
  receive();assert(d.sourceMatching&&d.sourceHeartbeat&&d.fields[0].number==1&&d.fields[4].fresh&&d.fields[4].number==0);
  profile["source_state"]="mismatch";receive();assert(d.sourceMismatch&&!d.sourceHeartbeat&&!d.fields[0].fresh&&!d.fields[4].fresh&&d.sensorFresh[0]);
  profile["source_state"]="unverified";receive();assert(!d.sourceMatching&&!d.sourceHeartbeat);
  profile["source_state"]="matching";profile["presence"]="unknown";receive();assert(!d.fields[0].fresh&&d.sensorFresh[0]);
  profile["presence"]="heartbeat";link["source"]="HEARTBEAT_OTHER";receive();assert(!d.fields[0].fresh);
  link["source"]="HEARTBEAT";node["device_node_present"]=false;receive();assert(d.fields[0].fresh&&!d.sensorFresh[0]);
  node["device_node_present"]=true;node["fresh"]=false;receive();assert(d.sensorNode[0]&&!d.sensorFresh[0]);
  node["fresh"]=true;node["data_age_ms"]=3001;receive();assert(!d.sensorFresh[0]);node["data_age_ms"]=0;
  receive(3001);assert(!d.fields[0].fresh&&!d.sensorFresh[0]);
  link["value"]=nullptr;link["fresh"]=false;receive();assert(!d.fields[0].fresh&&d.sensorFresh[0]);
  MaintenanceEvidence g;g.tlsFresh=g.ownerAuthenticated=g.directPiAp=true;g.wifiDbm=-50;assert(!maintenanceConditions(g));
  puts("PASS legacy display, configured board, source mismatch/unknown, unplug, stale and genuine zero; independent sensor data, node-only, unavailable, UART silence fails closed.");
}
