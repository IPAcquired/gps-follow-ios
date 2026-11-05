#include "DisplayTelemetry.h"
#include "SessionPolicy.h"
#include "PhoneLocation.h"
#include <cassert>
#include <random>
#include <cstdio>
int main(){
  std::mt19937 rng(20261023);
  for(unsigned i=0;i<5000;++i){
    unsigned age=rng()%1001, transit=rng()%1501, now=rng();
    StaticJsonDocument<1536> doc;
    doc["schema"]=1;doc["authority"]="advisory_only";doc["generated_unix_ms"]=1792771200000ULL+i;
    auto hb=doc["h743"]["connected"];hb["value"]=true;hb["fresh"]=true;hb["age_ms"]=0;
    auto speed=doc["h743"]["groundspeed_mps"];speed["value"]=12.5;speed["fresh"]=true;speed["age_ms"]=age;
    DisplayTelemetry data;assert(data.accept(doc.as<JsonVariantConst>(),now,transit));
    bool valid=age+transit<=1000;
    assert(metricFresh(data.fields[4],data.received,now,1000)==valid);
    assert(!metricFresh(data.fields[4],data.received,now+1001,1000));
    assert(!data.accept(doc.as<JsonVariantConst>(),now+1)); // replay never extends validity
    assert(!data.fields[4].fresh);
    doc["generated_unix_ms"]=1792771300000ULL+i;speed["value"]=true;
    assert(data.accept(doc.as<JsonVariantConst>(),now+2));assert(!data.fields[4].fresh);
    SessionPolicy session;session.response(false,401,now);
    assert(!session.canLogin(now+4999));assert(session.canLogin(now+5000));
    assert(session.response(true,200,now+5001)==AuthResponse::None);
    session.response(false,429,now+5002);assert(!session.canRequest(now+20001));assert(session.canRequest(now+20002));
    SessionPolicy bad;bad.response(true,401,now);assert(!bad.canLogin(now+60000));
    PhoneLocation phone;phone.active=true;phone.seq=1;phone.epoch[0]='a';phone.received=now;phone.age=age;
    assert(phoneLocationFresh(phone,now+transit)==(age+transit<=2500));
    assert(!phoneLocationFresh(phone,now+2501));
  }
  puts("{\"cases\":5000,\"seed\":20261023,\"passed\":true,\"checks\":[\"latency_and_expiry\",\"replay_rejection\",\"malformed_numeric_type\",\"session_reauthentication\",\"rate_cooldown\",\"bad_password_stops\",\"millisecond_wrap\",\"phone_expiry\"],\"hardware_writes\":0}");
}
