#pragma once
#include <ArduinoJson.h>
#include <stdint.h>
#include <math.h>
#include <string.h>
#include <stdio.h>
#include <initializer_list>
#ifdef ARDUINO_ARCH_ESP32
static_assert(JSON_OBJECT_SIZE(1)==16,"Recheck target JSON slot budget");
#endif
struct MetricSpec{const char* key;const char* label;const char* unit;uint32_t ttl;double low,high;uint8_t decimals;bool pi;};
static const MetricSpec METRICS[]={
 {"connected","Controller link","",3000,0,1,0,false},{"armed","Armed","",3000,0,1,0,false},{"mode","Mode","",3000,0,0,0,false},{"system_status","System status","",3000,0,255,0,false},
 {"groundspeed_mps","Ground speed","m/s",2000,0,200,1,false},{"airspeed_mps","Air speed","m/s",2000,0,200,1,false},{"climb_mps","Climb","m/s",2000,-100,100,1,false},{"altitude_msl_m","MSL altitude","m",2000,-1000,20000,1,false},
 {"relative_altitude_m","Relative altitude","m",2000,-1000,20000,1,false},{"latitude_deg","Drone latitude","deg",2000,-90,90,6,false},{"longitude_deg","Drone longitude","deg",2000,-180,180,6,false},{"heading_deg","Heading","deg",2000,0,360,1,false},
 {"roll_deg","Roll","deg",2000,-180,180,1,false},{"pitch_deg","Pitch","deg",2000,-180,180,1,false},{"yaw_deg","Yaw","deg",2000,-360,360,1,false},{"battery_voltage_v","Battery voltage","V",5000,1,80,2,false},
 {"battery_current_a","Battery current","A",5000,-200,1000,2,false},{"battery_remaining_percent","Battery remaining","%",5000,0,100,0,false},{"battery_consumed_mah","Consumed","mAh",5000,0,1000000,0,false},
 {"gps_fix_type","GPS fix type","",2000,0,8,0,false},{"gps_satellites","GPS satellites","",2000,0,254,0,false},{"gps_hdop","GPS HDOP","",2000,0,1000,2,false},{"gps_horizontal_accuracy_m","GPS accuracy","m",2000,0,100000,2,false},
 {"rc_rssi_raw","RC RSSI (raw)","raw",2000,0,254,0,false},{"rc_channels_count","RC channels","",2000,0,18,0,false},{"ekf_flags","EKF flags","raw",2000,0,65535,0,false},
 {"on_ground","On ground","",1000,0,1,0,false},{"landed_state","Landed state","raw",1000,0,4,0,false},
 {"load_1m","Load 1 minute","",10000,0,1000,2,true},{"load_5m","Load 5 minutes","",10000,0,1000,2,true},{"load_15m","Load 15 minutes","",10000,0,1000,2,true},
 {"cpu_busy_percent","CPU busy","%",10000,0,100,1,true},{"cpu_max_temperature_c","CPU max temp","C",10000,-40,150,1,true},{"memory_total_bytes","Memory total","bytes",10000,0,1e12,0,true},{"memory_available_bytes","Memory available","bytes",10000,0,1e12,0,true},
 {"uptime_seconds","Pi uptime","s",10000,0,1e12,0,true},{"wifi_rssi_dbm","Pi Wi-Fi RSSI","dBm",10000,-127,0,0,true},{"wifi_ssid","Pi Wi-Fi SSID","",10000,0,0,0,true},{"ai_process_active","AI process","",15000,0,1,0,true},{"ai_state","AI state (not health)","",15000,0,0,0,true}
 ,{"board_voltage_v","Controller volts","V",5000,0.001,65.534,2,false},
 {"servo_voltage_v","Servo rail volts","V",5000,0.001,65.534,2,false},
 {"power_flags","Power flags","raw",5000,0,65535,0,false},
 {"battery_power_w","Battery power","W",5000,0,80000,2,false},
 {"board_current_a","Pi total current","A",5000,0,100,2,true},
 {"usb_port_current_a","Pi port currents","A",5000,0,100,2,true},
 {"input_voltage_v","Pi input volts","V",5000,0,60,2,true}
};
constexpr size_t METRIC_COUNT=sizeof(METRICS)/sizeof(METRICS[0]);
inline void displayTelemetryFilter(JsonDocument& filter){
  filter["schema"]=true;filter["authority"]=true;filter["generated_unix_ms"]=true;filter["updated_unix"]=true;
  for(const char* key:{"configured_model","configured_board_id","source_state","presence"})filter["controller_profile"][key]=true;
  // Both producer maps contain the same metric wrappers. Keep only the three
  // public value fields; the receiver still selects metrics by their exact names.
  // ArduinoJson's named filter takes precedence over its '*' fallback.
  for(const char* key:{"value","fresh","age_ms"}){
    filter["h743"]["*"][key]=true;filter["pi"]["*"][key]=true;
    filter["h743"]["connected"][key]=true;
  }
  filter["h743"]["connected"]["source"]=true;
  const char* sensors[]={"rplidar","matrix_lidar","camera"};
  for(const char* key:sensors){auto item=filter["sensor_health"][key];item["status"]=true;item["fresh"]=true;item["device_node_present"]=true;item["data_age_ms"]=true;}
  for(const char* key:{"status","authority","position_is_drone_gps","transport","age_ms","accuracy_m","lat","lon"})filter["follow_location"][key]=true;
  filter["rc_channels"]["values"]=true;filter["rc_channels"]["fresh"]=true;filter["rc_channels"]["age_ms"]=true;
  auto range=filter["rangefinders"][0];range["id"]=true;for(const char* key:{"orientation","distance_cm"}){range[key]["value"]=true;range[key]["fresh"]=true;range[key]["age_ms"]=true;}
  auto message=filter["messages"][0];for(const char* key:{"text","severity","time_utc","age_ms"})message[key]=true;
  auto fault=filter["faults"][0];for(const char* key:{"component","text","age_ms"})fault[key]=true;
  for(const char* key:{"fresh","age_ms","sample_succeeded","units"})filter["pi_service_health"][key]=true;
}
struct DisplayMetric{double number=NAN;uint32_t age=0;bool fresh=false;char text[40]={};};
inline bool metricFresh(const DisplayMetric& value,uint32_t received,uint32_t now,uint32_t ttl){
  return value.fresh&&uint32_t(now-received)<=ttl&&value.age<=ttl-uint32_t(now-received);
}
struct DisplayTelemetry {
  const char* rejection="none";
  bool profileProvided=false,sourceMatching=false,sourceMismatch=false,sourceHeartbeat=false;
  bool phoneFresh=false,phoneBrowser=false;uint32_t phoneAge=0;double phoneAccuracy=NAN;
  DisplayMetric fields[METRIC_COUNT];uint32_t received=0,revision=0;uint64_t generated=0;
  uint32_t sensorAge[3]={};bool sensorFresh[3]={},sensorNode[3]={};char sensorState[3][28]={};
  char faults[6][121]={};uint8_t faultCount=0;
  uint16_t rc[18]={};uint32_t rcAge[18]={};bool rcFresh[18]={};
  struct Range{int id=0,orientation=-1;double cm=NAN;uint32_t age=0;bool fresh=false;} ranges[8];uint8_t rangeCount=0;
  char failedUnits[8][65]={};uint8_t unitCount=0;bool serviceCheckFresh=false;uint32_t serviceAge=0;
  void invalidate(){profileProvided=false;sourceMatching=sourceMismatch=sourceHeartbeat=false;phoneFresh=false;serviceCheckFresh=false;unitCount=0;for(auto& field:fields)field.fresh=false;for(int i=0;i<3;++i)sensorFresh[i]=false;for(int i=0;i<18;++i)rcFresh[i]=false;rangeCount=faultCount=0;++revision;}
  bool accept(JsonVariantConst doc,uint32_t now,uint32_t transportAge=0,uint64_t nowUtcMs=0){
    if(!doc["schema"].is<int>()||doc["schema"].is<bool>()||doc["schema"].as<int>()!=1||doc["authority"]!="advisory_only"||!doc["generated_unix_ms"].is<uint64_t>()||doc["generated_unix_ms"].is<bool>()){rejection="schema";invalidate();return false;}
    uint64_t stamp=doc["generated_unix_ms"];
    if(stamp<1792022400000ULL){rejection="epoch";invalidate();return false;}
    if(generated&&stamp<=generated){rejection="duplicate_or_reversed";invalidate();return false;}
    if(nowUtcMs&&(stamp>nowUtcMs+1500||nowUtcMs>stamp+5000)){rejection="clock_window";invalidate();return false;}
    DisplayTelemetry next;next.received=now;next.generated=stamp;next.revision=revision+1;
    const auto profile=doc["controller_profile"];
    next.profileProvided=!profile.isNull();
    next.sourceMismatch=next.profileProvided&&(profile["source_state"]=="mismatch"||profile["configured_model"]!="CORVON743V2"||
      !profile["configured_board_id"].is<int>()||profile["configured_board_id"].as<int>()!=1229);
    next.sourceMatching=next.profileProvided&&!next.sourceMismatch&&profile["source_state"]=="matching";
    next.sourceHeartbeat=doc["h743"]["connected"]["source"]=="HEARTBEAT"&&(!next.profileProvided||(next.sourceMatching&&profile["presence"]=="heartbeat"));
    for(size_t i=0;i<METRIC_COUNT;++i){const auto& spec=METRICS[i];if(!spec.pi&&!next.sourceHeartbeat)continue;auto wrapper=doc[spec.pi?"pi":"h743"][spec.key];auto val=wrapper["value"];
      if(!wrapper["fresh"].is<bool>()||!wrapper["fresh"].as<bool>()||!wrapper["age_ms"].is<uint32_t>()||wrapper["age_ms"].is<bool>()||val.isNull())continue;
      uint32_t age=wrapper["age_ms"];if(age>spec.ttl||transportAge>spec.ttl-age)continue;age+=transportAge;
      auto& out=next.fields[i];out.age=age;
      if((i==0||i==1||i==26||i==38)&&!val.is<bool>())continue;
      if(i!=0&&i!=1&&i!=26&&i!=38&&val.is<bool>())continue;
      if(val.is<bool>()){out.number=val.as<bool>()?1:0;snprintf(out.text,sizeof(out.text),"%s",val.as<bool>()?"YES":"NO");}
      else if(val.is<double>()){double n=val.as<double>();if(!isfinite(n)||n<spec.low||n>spec.high)continue;out.number=n;
        if(!strcmp(spec.unit,"bytes"))snprintf(out.text,sizeof(out.text),"%.1f MiB",n/1048576.0);
        else snprintf(out.text,sizeof(out.text),"%.*f%s%s",int(spec.decimals),n,spec.unit[0]?" ":"",spec.unit);
      }else if(val.is<const char*>()&&(!strcmp(spec.key,"mode")||!strcmp(spec.key,"system_status")||!strcmp(spec.key,"wifi_ssid")||!strcmp(spec.key,"ai_state"))){const char* text=val.as<const char*>();if(strlen(text)>100)continue;snprintf(out.text,sizeof(out.text),"%s",text);}
      else continue;
      out.fresh=true;
    }
    const char* sensors[]={"rplidar","matrix_lidar","camera"};
    for(int i=0;i<3;++i){auto sensor=doc["sensor_health"][sensors[i]];snprintf(next.sensorState[i],sizeof(next.sensorState[i]),"%s",sensor["status"]|"unavailable");
      next.sensorNode[i]=sensor["device_node_present"]==true;
      if(next.sensorNode[i]&&sensor["status"]=="fresh_data"&&sensor["fresh"]==true&&sensor["data_age_ms"].is<uint32_t>()&&!sensor["data_age_ms"].is<bool>()&&sensor["data_age_ms"].as<uint32_t>()<=3000&&transportAge<=3000-sensor["data_age_ms"].as<uint32_t>()){next.sensorFresh[i]=true;next.sensorAge[i]=sensor["data_age_ms"].as<uint32_t>()+transportAge;}}
    for(auto msg:doc["messages"].as<JsonArrayConst>()){
      if(next.faultCount>=3)break;
      const char* content=msg["text"]|"";
      if(!msg["age_ms"].is<uint32_t>()||msg["age_ms"].as<uint32_t>()>10000||strlen(content)>120||!strlen(content))continue;
      snprintf(next.faults[next.faultCount++],121,"FC: %.114s",content);
    }
    for(auto fault:doc["faults"].as<JsonArrayConst>()){
      if(next.faultCount>=6)break;
      const char* content=fault["text"]|"";const char* component=fault["component"]|"unknown";
      if((!fault["age_ms"].isNull()&&(!fault["age_ms"].is<uint32_t>()||fault["age_ms"].as<uint32_t>()>15000))||strlen(content)>120||!strlen(content))continue;
      snprintf(next.faults[next.faultCount++],121,"%s: %.105s",component,content);
    }
    auto channels=doc["rc_channels"];
    for(int i=0;i<18;++i){auto value=channels["values"][i],age=channels["age_ms"][i];
      if(next.sourceHeartbeat&&channels["fresh"][i]==true&&value.is<uint16_t>()&&!value.is<bool>()&&value.as<uint16_t>()>0&&value.as<uint16_t>()<65535&&age.is<uint32_t>()&&age.as<uint32_t>()<=2000&&transportAge<=2000-age.as<uint32_t>()){next.rc[i]=value;next.rcAge[i]=age.as<uint32_t>()+transportAge;next.rcFresh[i]=true;}}
    for(auto item:doc["rangefinders"].as<JsonArrayConst>()){
      if(!next.sourceHeartbeat)break;
      if(next.rangeCount>=8)break;
      auto distance=item["distance_cm"],ori=item["orientation"];auto& out=next.ranges[next.rangeCount++];out.id=item["id"]|0;
      if(ori["fresh"]==true&&ori["value"].is<int>()&&ori["value"].as<int>()>=0&&ori["value"].as<int>()<=255)out.orientation=ori["value"];
      if(distance["fresh"]==true&&distance["age_ms"].is<uint32_t>()&&distance["age_ms"].as<uint32_t>()<=2000&&distance["value"].is<double>()&&!distance["value"].is<bool>()){
        double cm=distance["value"];uint32_t age=distance["age_ms"];if(isfinite(cm)&&cm>0&&cm<100000&&transportAge<=2000-age){out.cm=cm;out.age=age+transportAge;out.fresh=true;}}}
    auto services=doc["pi_service_health"];
    if(services["fresh"]==true&&services["sample_succeeded"]==true&&services["age_ms"].is<uint32_t>()&&services["age_ms"].as<uint32_t>()<=15000&&transportAge<=15000-services["age_ms"].as<uint32_t>()){
      next.serviceCheckFresh=true;next.serviceAge=services["age_ms"].as<uint32_t>()+transportAge;
      for(auto unit:services["units"].as<JsonArrayConst>()){if(next.unitCount>=8)break;const char* name=unit|"";if(strlen(name)&&strlen(name)<=64)snprintf(next.failedUnits[next.unitCount++],65,"%s",name);}}
    auto phone=doc["follow_location"];
    if(phone["status"]=="fresh"&&phone["authority"]=="advisory_only"&&phone["position_is_drone_gps"].is<bool>()&&phone["position_is_drone_gps"]==false&&phone["age_ms"].is<uint32_t>()&&!phone["age_ms"].is<bool>()&&phone["accuracy_m"].is<double>()&&!phone["accuracy_m"].is<bool>()&&phone["lat"].is<double>()&&!phone["lat"].is<bool>()&&phone["lon"].is<double>()&&!phone["lon"].is<bool>()){
      uint32_t age=phone["age_ms"];double accuracy=phone["accuracy_m"],lat=phone["lat"],lon=phone["lon"];
      if(age<3000&&transportAge<3000-age&&isfinite(accuracy)&&accuracy>0&&accuracy<=30&&isfinite(lat)&&lat>=-90&&lat<=90&&isfinite(lon)&&lon>=-180&&lon<=180){next.phoneFresh=true;next.phoneAge=age+transportAge;next.phoneAccuracy=accuracy;next.phoneBrowser=phone["transport"]=="phone_browser_wifi";}
    }
    *this=next;return true;
  }
};
