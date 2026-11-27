#pragma once
#include "Storage.h"
#include "WiredDesktopProtocol.h"

class XiaoLights {
 public:
  struct Config{uint8_t mode,color,brightness,pattern,speed,yellow;
    Config(uint8_t m=0,uint8_t c=0,uint8_t b=64,uint8_t p=0,uint8_t s=29,uint8_t y=0):mode(m),color(c),brightness(b),pattern(p),speed(s),yellow(y){} };
  Config confirmed;
  uint8_t rgb[3]{},duty=0,power=0;
  uint32_t revision=0,acknowledgements=0,timeouts=0;
  bool valid=false;
  enum class ApplyError:uint8_t { None,NoReply,Rejected,Driver,InvalidReply };
  ApplyError applyError=ApplyError::None;
  const char* applyNote()const{
    switch(applyError){
      case ApplyError::NoReply:return "Setting unconfirmed. Check the cable and retry.";
      case ApplyError::Rejected:return "Setting rejected. Check the choice and retry.";
      case ApplyError::Driver:return "Setting not applied: XIAO RGB driver unavailable.";
      case ApplyError::InvalidReply:return "Setting unconfirmed. Invalid XIAO reply; retry.";
      default:return "";
    }
  }
  bool ready()const{return valid&&uint32_t(millis()-seen_)<2400;}
  bool pending()const{return stage_!=0;}
  bool physicallySilent()const{return blankMisses_>=3&&uint32_t(millis()-firstBlankMiss_)>=1800;}
  void beginDetachWatch(){blankMisses_=0;blankAfterRetry_=false;}
  const Config& editBase()const{return queued_?next_:(stage_&&write_?wanted_:confirmed);}
  void probe(bool passive=false){if(!stage_){start(false,confirmed);passive_=passive;}}
  bool set(const Config& c){
    if(!ready()||!sane(c))return false;
    if(stage_&&write_){
      if(!memcmp(&editBase(),&c,sizeof c))return false;
      next_=c;queued_=true;return true;
    }
    // A periodic read must never swallow a deliberate menu adjustment.
    start(true,c);return true;
  }
  void service(bool watching){
    using namespace wireddesktop;
    uint32_t now=millis();
    if(valid&&!ready()){
      valid=false;queued_=false;if(write_&&stage_){applyResult(ApplyError::NoReply);stage_=0;}++revision;
    }
    if(!stage_&&watching&&uint32_t(now-probed_)>=1000)probe();
    if(!stage_)return;
    if(uint32_t(now-started_)>=75){
      if(!retried_&&(!write_||ready())){
        // Repeating the absolute setting cannot toggle an output twice.
        retried_=true;started_=now;stage_=1;
      }else{
        // A lost reply leaves the last confirmed setting on screen until its
        // presence lease expires. Never replay old user intent after unplug.
        if(!write_&&blankAfterRetry_&&!heardReply_){
          if(!blankMisses_)firstBlankMiss_=now;
          if(blankMisses_<255)++blankMisses_;
        }
        if(write_)applyResult(ApplyError::NoReply);
        ++timeouts;stage_=0;queued_=false;probed_=now-750;return;
      }
    }
    if(stage_==2&&uint32_t(now-sent_)<(passive_?15u:3u))return;
    alignas(4) uint8_t q[BufferSize]{},r[BufferSize]{};
    if(stage_==1){memcpy(q,"DLQ1",4);q[4]=write_?1:2;put16(q+5,seq_);
      if(write_){q[7]=wanted_.mode;q[8]=wanted_.color;q[9]=wanted_.brightness;q[10]=wanted_.pattern;q[11]=wanted_.speed;q[12]=wanted_.yellow;}}
    else memcpy(q,"DLP1",4);
    put16(q+71,checksum(q,71));
    if(!wiredDesktopExchange(q,r,PacketSize))return; // Shared SD lock contention is not a missing cable.
    if(stage_==2){
      bool blank=r[0]==0||r[0]==255;
      for(unsigned i=1;blank&&i<PacketSize;++i)blank=r[i]==r[0];
      if(!blank){heardReply_=true;blankMisses_=0;}
      else if(retried_)blankAfterRetry_=true;
    }
    if(stage_==1){stage_=2;sent_=now;return;}
    sent_=now;
    if(memcmp(r,"DLR1",4)||get16(r+5)!=seq_||get16(r+71)!=checksum(r,71))return;
    stage_=0;
    Config c{r[7],r[8],r[9],r[10],r[11],r[12]};
    if(r[4]||!sane(c)||r[17]>1){
      if(write_)applyResult(r[4]==2?ApplyError::Driver:r[4]?ApplyError::Rejected:ApplyError::InvalidReply);
      queued_=false;probed_=now-750;return;
    }
    if(write_)applyResult(ApplyError::None);
    if(!valid||memcmp(&confirmed,&c,sizeof c))++revision;
    blankMisses_=0;++acknowledgements;valid=true;seen_=now;confirmed=c;memcpy(rgb,r+13,3);duty=r[16];power=r[17];
    if(queued_){
      queued_=false;
      if(memcmp(&next_,&confirmed,sizeof c))start(true,next_);
    }
  }
  static bool sane(const Config& c){return c.mode<6&&c.color<11&&c.pattern<4&&c.speed>=1&&c.speed<=100&&c.yellow<4;}
 private:
  void applyResult(ApplyError error){if(applyError!=error){applyError=error;++revision;}}
  Config wanted_,next_;uint16_t seq_=0;uint8_t stage_=0;
  bool write_=false,queued_=false,retried_=false,passive_=false;
  bool blankAfterRetry_=false,heardReply_=false;
  uint8_t blankMisses_=0;uint32_t firstBlankMiss_=0;
  uint32_t seen_=0,started_=0,sent_=0,probed_=0;
  void start(bool write,const Config& c){wanted_=c;write_=write;stage_=1;retried_=blankAfterRetry_=heardReply_=passive_=false;if(++seq_==0)++seq_;started_=probed_=millis();}
};
