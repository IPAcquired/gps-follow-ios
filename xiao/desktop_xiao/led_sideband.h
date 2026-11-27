#pragma once
#include "protocol.h"
#include "LightPattern.h"

namespace lamps {
struct Settings { uint8_t mode=0, color=0, brightness=64, beacon=0, speed=29, yellow=0; };
struct Output { uint8_t r=0,g=0,b=0,y=0,power=0; };

inline Output render(const Settings &s,uint32_t now,RainbowClock &clock) {
    if(s.mode!=3)clock.reset();
    const uint16_t hue=s.mode==3?clock.sample(now,s.speed):0;
    const auto rgb=lightPattern(s.mode,s.color,s.brightness,now,s.beacon,s.speed,hue);
    uint8_t peak=rgb.r>rgb.g?rgb.r:rgb.g;
    if(rgb.b>peak)peak=rgb.b;
    uint8_t yellow=0;
    if(s.yellow==1)yellow=s.brightness;
    if(s.yellow==2)yellow=peak;
    if(s.yellow==3){
        const uint32_t p=lightPeriod(s.speed);
        yellow=(!p||now%p<p/2)?s.brightness:0;
    }
    return {rgb.r,rgb.g,rgb.b,yellow,uint8_t(s.mode!=0 && s.brightness!=0)};
}
enum class Type { Other, Request, Poll, Invalid };
struct Command { uint16_t seq=0; bool set=false; Settings settings{}; uint8_t status=0; };
inline Type parse(const uint8_t *data,Command &q) {
    const bool query=!memcmp(data,"DLQ1",4),pull=!memcmp(data,"DLP1",4);
    if(!query&&!pull)return Type::Other;
    if(desktop::read16(data+71)!=desktop::crc(data,71))return Type::Invalid;
    for(unsigned i=pull?4:13;i<71;++i)if(data[i])return Type::Invalid;
    if(pull)return Type::Poll;
    q.seq=desktop::read16(data+5);
    if(!q.seq)return Type::Invalid;
    q.set=data[4]==1;
    q.settings={data[7],data[8],data[9],data[10],data[11],data[12]};
    const auto &s=q.settings;
    if(data[4]!=2 && (!q.set||s.mode>5||s.color>=LIGHT_COLOR_COUNT||s.beacon>3||
        s.speed<1||s.speed>LIGHT_SPEED_COUNT||s.yellow>3))q.status=1;
    return Type::Request;
}
inline void reply(uint8_t *out,uint16_t seq,uint8_t result,const Settings &s,const Output &v) {
    memset(out,0,desktop::FRAME);
    memcpy(out,"DLR1",4);out[4]=result;desktop::write16(out+5,seq);
    out[7]=s.mode;out[8]=s.color;out[9]=s.brightness;out[10]=s.beacon;out[11]=s.speed;out[12]=s.yellow;
    out[13]=v.r;out[14]=v.g;out[15]=v.b;out[16]=v.y;out[17]=v.power;
    desktop::write16(out+71,desktop::crc(out,71));
}
}
