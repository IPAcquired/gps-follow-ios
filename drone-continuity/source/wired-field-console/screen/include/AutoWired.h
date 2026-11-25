#pragma once
#include <TFT_eSPI.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "PairChannel.h"
#include "WiredNotices.h"
#include "WiredDesktopProtocol.h"
#include "Storage.h"
#include "WiredPictures.h"
#include "WiredKeys.h"

// The paired Pi publishes a different generation for each USB attachment.
// These beacons identify the display protocol. They never authorize data.
class WiredPresence {
 public:
  bool observe(uint32_t gen, uint16_t seq, uint32_t now) {
    if (!gen || !seq) return false;
    if (pending_ != gen || uint32_t(now - seen_) > 6000) {
      pending_ = gen; hits_ = 0; previous_ = 0;
    }
    seen_ = now;
    if (previous_ != seq) { previous_ = seq; if (hits_ < 2) ++hits_; }
    if (hits_ == 2) {
      const bool changed = current_ != gen;
      current_ = gen; present_ = true;
      return changed;
    }
    return false;
  }
  void seen(uint32_t now) { if (present_) seen_ = now; }
  void expire(uint32_t now) {
    if (uint32_t(now-seen_) > 6000) { present_ = false; hits_ = 0; pending_ = 0; }
  }
  void dismiss() { dismissed_ = current_; }
  void select() { dismissed_ = 0; }
  bool present() const { return present_; }
  bool dismissed() const { return current_ && dismissed_ == current_; }
  bool wanted() const { return present_ && !dismissed(); }
  uint32_t generation() const { return current_; }
 private:
  uint32_t pending_=0, current_=0, seen_=0, dismissed_=0;
  uint16_t previous_=0;
  uint8_t hits_=0;
  bool present_=false;
};

class AutoWired {
 public:
  WiredPictures pictures;
  WiredKeys keys;
  bool (*commitGuard)()=nullptr;
  uint32_t droppedInputs=0,fastFallbacks=0,fastTransfers=0,crcErrors=0,fastPromotions=0,sidebandReplies=0;
  bool fastSpi()const{return open_&&!useUsb_&&live_&&channel_.established()&&!slowOnly_;}
  bool bulkSpi(bool penDown,bool sideband)const{
    return fastSpi()&&pictures.receivingJpeg()&&!penDown&&!sideband&&!keys.shown&&(!keys.head()||keys.head()->opcode==0x27);
  }
  bool enroll(const uint8_t key[32]) { enrolled_=channel_.begin(key); return enrolled_; }
  bool enrolled() const { return enrolled_; }
  bool active() const { return open_; }
  bool present() const { return selected().present(); }
  bool dismissed() const { return selected().dismissed(); }
  bool usbActive() const { return useUsb_; }
  bool established() const { return channel_.established(); }
  bool live() const { return live_; }
  uint8_t zoomLevel()const{return zoomLevel_;}
  bool zoomWaiting()const{return zoomRequest_!=0;}
  uint32_t pixelsDrawn() const { return pixels_; }
  uint32_t touches() const { return touches_; }
  uint32_t paints() const { return paints_; }
  uint32_t handshakes() const { return handshakes_; }
  bool canOpen() const { return enrolled_ && selected().wanted(); }
  void select() { spi_.select();usb_.select(); }
  void dismiss(){spi_.dismiss();usb_.dismiss();}
  void setNotice(TFT_eSPI& lcd,const wirednotice::Notice& n){
    if(notice_.level==n.level&&!strcmp(notice_.text,n.text))return;
    notice_=n;
    if(open_)bar(lcd);
  }

  void open(TFT_eSPI& lcd) {
    open_ = true;
    resetSession();
    pictures.acquire();
    waitLift_ = true; back_ = false;
    drawPage(lcd);
  }
  void close(TFT_eSPI& lcd,bool dismissed) {
    if (!open_) return;
    if (dismissed) {spi_.dismiss();usb_.dismiss();}
    if (channel_.established()) {
      uint8_t clear[5]={0x23};
      put32(clear+1, channel_.rxCounter());
      if (channel_.wrap(clear,sizeof clear,up_,upLen_)) {
        alignas(4) uint8_t q[wireddesktop::BufferSize]{},r[wireddesktop::BufferSize]{};
        if(useUsb_){memcpy(usbEnd_,up_,upLen_);usbEndLen_=upLen_;usbEndAt_=millis();}
        else {makeRequest(q); wiredDesktopExchange(q,r,wireddesktop::PacketSize);}
      }
    }
    resetSession();pictures.release();open_=false;
    lcd.fillScreen(TFT_BLACK);
  }
  // Returns false to leave the page. A physical Back never generates a remote tap.
  bool step(TFT_eSPI& lcd,uint16_t threshold,bool permitSession,bool penDown=true,bool otherSpi=false) {
    const uint32_t now=millis();
    spi_.expire(now);usb_.expire(now);
    bool nextUsb=!spi_.present() && usb_.present();
    if(nextUsb!=useUsb_){
      resetSession();useUsb_=nextUsb;waitLift_=true;back_=false;usbEndLen_=0;
      if(open_)drawPage(lcd);
    }
    if (open_ && (!permitSession || !selected().wanted())) { close(lcd,false); return false; }
    if (open_ && live_ && (!channel_.established() || uint32_t(now-heartbeat_) >= 2800)) {
      resetSession(); waitLift_ = true; drawPage(lcd);
    } else if (open_ && channel_.established() && !live_ && uint32_t(now-readySince_) >= 3200) {
      resetSession(); waitLift_=true; drawPage(lcd);
    } else if (open_ && proofPending_ && uint32_t(now-proofAt_)>=5000) {
      resetSession();
    }
    if (open_ && !readTouch(lcd,threshold,penDown)) { close(lcd,true); return false; }
    if(open_&&keys.full){++droppedInputs;resetSession();waitLift_=true;drawPage(lcd);}
    if (open_ && !upLen_) {
      up_[0]=0x50; put32(up_+1,selected().generation()); upLen_=5;
    }
    if(otherSpi)return true; // An addressed LED receipt must reach its own local consumer.
    if(fastSpi()&&uint32_t(now-progressAt_)>1500)downshift(now);
    if(slowOnly_&&open_&&!useUsb_&&live_&&channel_.established()&&slowValid_>=12&&
        uint32_t(now-lastDownshift_)>=cooldown_&&uint32_t(now-progressAt_)<600){
      slowOnly_=false;fastMisses_=slowValid_=0;++fastPromotions;
    }
    const bool fast=fastSpi();
    const uint32_t interval = open_ && !useUsb_ ? (bulkSpi(penDown,otherSpi)?2:fast?3:8) : 230;
    if (uint32_t(now-lastPoll_) < interval) return true;
    lastPoll_=now;
    alignas(4) uint8_t q[wireddesktop::BufferSize]{}, r[wireddesktop::BufferSize]{};
    makeRequest(q);
    if(wiredDesktopTransfer(q,r,wireddesktop::PacketSize,fast)){
      bool crcOK=wireddesktop::get16(r+71)==wireddesktop::checksum(r,71);
      if(crcOK&&!memcmp(r,"DLR1",4)){++sidebandReplies;return true;}
      const bool valid=crcOK&&!memcmp(r,"DTR1",4)&&
             ((r[4]==0&&!wireddesktop::get16(r+7))||(r[4]==1&&wireddesktop::get16(r+5)&&
               wireddesktop::get16(r+7)&&wireddesktop::get16(r+7)<=62));
      if(fast){
        ++fastTransfers;
        if(valid)fastMisses_=0;
        else{if(!crcOK)++crcErrors;if(++fastMisses_>=2)downshift(now);}
      }else if(slowOnly_){if(!valid)slowValid_=0;else if(slowValid_<12)++slowValid_;}
      if(valid)receive(lcd,r,now,permitSession);
    }
    return true;
  }
  void usbExchange(TFT_eSPI& lcd,uint16_t seq,const uint8_t* body,size_t len,bool permit,
                   uint16_t& ack,bool& busy,uint8_t* up,size_t& upLen) {
    if(len&&len<=62&&seq) record(lcd,seq,body,len,millis(),permit,true);
    busy=spi_.present();ack=ackUsb_;upLen=0;
    if(busy) return;
    if(open_ && useUsb_ && permit && upLen_){memcpy(up,up_,upLen_);upLen=upLen_;}
    else if(usbEndLen_ && uint32_t(millis()-usbEndAt_)<1000){
      memcpy(up,usbEnd_,usbEndLen_);upLen=usbEndLen_;
    }
  }
 private:
  PairChannel channel_;
  WiredPresence spi_,usb_;
  wirednotice::Notice notice_;
  bool useUsb_=false;
  WiredPresence& selected(){return useUsb_?usb_:spi_;}
  const WiredPresence& selected() const{return useUsb_?usb_:spi_;}
  bool enrolled_=false, open_=false, live_=false, waitLift_=false, back_=false;
  bool zoomMenu_=false;
  uint8_t zoomLevel_=1,nextZoom_=1;
  uint16_t zoomRequest_=0;
  uint16_t focusRequest_=0;
  bool focusHint_=false;
  static constexpr unsigned ZoomTop=220;
  uint32_t progressAt_=0,lastDownshift_=0,cooldown_=1000;
  bool slowOnly_=false;uint8_t fastMisses_=0,slowValid_=0;
  void downshift(uint32_t now){
    slowOnly_=true;lastDownshift_=now;++fastFallbacks;fastMisses_=slowValid_=0;
    if(cooldown_<16000)cooldown_*=2;
  }
  bool proofPending_=false,firstPaint_=true;
  uint32_t proofAt_=0;
  uint32_t lastPoll_=0, heartbeat_=0, readySince_=0, pixels_=0, touches_=0, paints_=0, handshakes_=0;
  uint16_t ackSpi_=0,ackUsb_=0, event_=0, x_=0,y_=0;
  uint8_t state_=0, up_[57]{},usbEnd_[57]{};
  size_t upLen_=0,usbEndLen_=0;
  uint32_t usbEndAt_=0;
  static uint32_t get32(const uint8_t* p) {
    return uint32_t(p[0])<<24|uint32_t(p[1])<<16|uint32_t(p[2])<<8|p[3];
  }
  static void put32(uint8_t* p,uint32_t value) {
    p[0]=value>>24;p[1]=value>>16;p[2]=value>>8;p[3]=value;
  }
  void resetSession() {
    resetLocalInput();pictures.clearView();firstPaint_=true;channel_.reset(); live_=false; proofPending_=false; heartbeat_=readySince_=0; upLen_=0; state_=0; event_=0;
    if(useUsb_)ackUsb_=0;else ackSpi_=0;
  }
  void resetLocalInput(){keys.reset();zoomMenu_=false;zoomLevel_=nextZoom_=1;zoomRequest_=focusRequest_=0;focusHint_=false;}
  void makeRequest(uint8_t* q) const {
    wireddesktop::Touch neutral;
    wireddesktop::makeRequest(q,neutral,ackSpi_);
    if (open_ && !useUsb_ && upLen_ && upLen_<=57) {
      q[13]=upLen_; memcpy(q+14,up_,upLen_);
      wireddesktop::put16(q+71,wireddesktop::checksum(q,71));
    }
  }
  void drawPage(TFT_eSPI& lcd) {
    lcd.fillScreen(TFT_BLACK);lcd.setTextColor(TFT_WHITE,TFT_BLACK);
    lcd.drawString("Orange Pi controller",16,24,4);
    lcd.drawString("Waiting for paired Pi authorization",16,89,2);
    bar(lcd);
  }
  void bar(TFT_eSPI& lcd) {
    lcd.fillRect(0,wireddesktop::Height,480,24,TFT_NAVY);
    lcd.setTextColor(TFT_WHITE,TFT_NAVY);lcd.drawString("< Back",8,300,2);
    if(notice_.level==wirednotice::None){
      const char* status=firstPaint_?"Loading desktop":focusHint_?"Tap field, reopen keys":focusRequest_?"Checking focus":"Paired desktop";
      lcd.drawString(live_ ? status : (useUsb_?"Direct Pi USB":"XIAO connected"),94,300,2);
    }else{
      char lines[125]{};
      snprintf(lines,sizeof lines,"%s: %.110s",wirednotice::label(notice_.level),notice_.text);
      for(char* c=lines;*c;++c)if(uint8_t(*c)<32||uint8_t(*c)>126)*c=' ';
      uint16_t bg=notice_.level>=wirednotice::Error?0x7800:0xff20;
      lcd.fillRect(88,wireddesktop::Height,live_?228:392,24,bg);
      lcd.setTextColor(notice_.level>=wirednotice::Error?TFT_WHITE:TFT_BLACK,bg);
      const unsigned cols=live_?37:50;
      if(strlen(lines)>cols){lines[2*cols]=0;lcd.drawString(lines+cols,92,309,1);lines[cols]=0;}
      lcd.drawString(lines,92,299,1);
    }
    if(live_){
      lcd.fillRect(316,296,164,24,TFT_NAVY);lcd.setTextColor(TFT_WHITE,TFT_NAVY);
      char label[12];snprintf(label,sizeof label,"Zoom %ux",unsigned(zoomLevel_));
      lcd.drawString(zoomRequest_?"Updating":label,320,299,2);
      lcd.drawString(keys.shown?"Hide keys":"Keyboard",408,299,2);
    }
  }
  bool ackOrTouch(bool caps=false) {
    uint8_t clear[35]{};size_t len=5;
    if(const auto* e=keys.head()){
      clear[0]=e->opcode;wireddesktop::put16(clear+1,e->seq);
      if(e->opcode==0x22){
        clear[3]=e->kind;wireddesktop::put16(clear+4,e->x);wireddesktop::put16(clear+6,e->y);
        put32(clear+8,channel_.rxCounter());len=12;
      }else{
        put32(clear+3,channel_.rxCounter());len=7;
        if(e->opcode==0x24){clear[7]=e->kind;memcpy(clear+8,e->value,e->len);len=8+e->len;}
        if(e->opcode==0x27){clear[7]=e->kind;len=8;}
      }
    }else if(caps){
      clear[0]=0x25;clear[1]=1;clear[2]=pictures.flags()|2|8|16;put32(clear+3,channel_.rxCounter());len=7;
    }else{clear[0]=0x21;put32(clear+1,channel_.rxCounter());}
    return channel_.wrap(clear,len,up_,upLen_);
  }
  void event(uint8_t state,uint16_t x,uint16_t y){
    if(!live_||!channel_.established())return;
    bool move=state==1&&state_==1;state_=state;x_=x;y_=y;
    if(keys.touch(state,x,y,move,event_)){++touches_;if(!ackOrTouch())keys.full=true;}
  }
  void toggleKeys(TFT_eSPI& lcd){
    if(!live_||!channel_.established()||zoomRequest_||focusRequest_||firstPaint_)return;
    if(!keys.shown){
      if(keys.queue(0x28,0,"",event_)){focusRequest_=event_;focusHint_=false;if(!ackOrTouch())keys.full=true;}
    }else{keys.shown=false;lcd.fillRect(0,WiredKeys::Top,480,296-WiredKeys::Top,TFT_BLACK);
      if(keys.queue(0x26,0,"",event_)&&!ackOrTouch())keys.full=true;}
    bar(lcd);
  }
  void zoomPanel(TFT_eSPI& lcd){
    static const char* labels[]={"1x / Reset","2x","3x","Left","Right","Up","Down","Done"};
    for(unsigned i=0;i<8;++i){
      bool scale=i<3;unsigned w=scale?160:96,x=scale?i*w:(i-3)*w,y=scale?ZoomTop:258;
      uint16_t bg=scale&&zoomLevel_==i+1?TFT_NAVY:0x2104;
      lcd.fillRect(x,y,w,38,TFT_BLACK);lcd.fillRect(x+1,y+1,w-2,36,bg);
      lcd.setTextColor(TFT_WHITE,bg);lcd.drawString(labels[i],x+8,y+10,2);
    }
  }
  void toggleZoom(TFT_eSPI& lcd){
    if(!live_||!channel_.established()||zoomRequest_||focusRequest_||firstPaint_)return;
    if(keys.shown)toggleKeys(lcd);
    zoomMenu_=!zoomMenu_;
    if(zoomMenu_)zoomPanel(lcd);
    else{
      lcd.fillRect(0,ZoomTop,480,296-ZoomTop,TFT_BLACK);
      if(keys.queue(0x26,0,"",event_)&&!ackOrTouch())keys.full=true;
    }
    bar(lcd);
  }
  void chooseZoom(TFT_eSPI& lcd,unsigned x,unsigned y){
    if(zoomRequest_)return;
    unsigned command=y<258?x/160:3+x/96;
    if(command==7){toggleZoom(lcd);return;}
    if(command>6||(command>=3&&zoomLevel_==1))return;
    if(keys.queue(0x27,uint8_t(command),"",event_)){
      // The Pi repaints the entire viewport and acknowledges this event only
      // after committing it. Keep the old image and block input in between.
      zoomRequest_=event_;nextZoom_=command<3?uint8_t(command+1):zoomLevel_;
      zoomMenu_=false;if(!ackOrTouch())keys.full=true;bar(lcd);
    }
  }
  bool readTouch(TFT_eSPI& lcd,uint16_t threshold,bool penDown) {
    uint16_t x=0,y=0;bool down=penDown&&lcd.getTouch(&x,&y,threshold);
    if (!down) {
      if (back_) return false;
      waitLift_=false;
      if (state_==1)event(2,x_,y_);
    } else if(!waitLift_ && !back_) {
      if (y>=wireddesktop::Height) {
        if (state_==1) { event(2,x_,y_); waitLift_=true; }
        else if (x<84) back_=true;
        else if(x>=404&&live_){toggleKeys(lcd);waitLift_=true;}
        else if(x>=316&&live_){toggleZoom(lcd);waitLift_=true;}
        else waitLift_=true;
      } else if(zoomRequest_||focusRequest_){waitLift_=true;}
      else if(zoomMenu_&&y>=ZoomTop){
        if(state_==1)event(2,x_,y_);else chooseZoom(lcd,x,y);
        waitLift_=true;
      } else if(keys.shown&&y>=WiredKeys::Top){
        if(state_==1)event(2,x_,y_);
        else if(!keys.press(lcd,x,y,event_))toggleKeys(lcd);
        else if(!ackOrTouch())keys.full=true;
        waitLift_=true;
      } else if (live_ && x<wireddesktop::Width && (state_!=1||x!=x_||y!=y_)) event(1,x,y);
      else if (!live_) waitLift_=true;
    }
    return true;
  }
  void receive(TFT_eSPI& lcd,const uint8_t* r,uint32_t now,bool permit) {
    using namespace wireddesktop;
    if (memcmp(r,"DTR1",4)||get16(r+71)!=checksum(r,71)||r[4]!=1) return;
    const uint16_t seq=get16(r+5), n=get16(r+7);
    if (!seq || !n || n>62) return;
    record(lcd,seq,r+9,n,now,permit,false);
  }
  void record(TFT_eSPI& lcd,uint16_t seq,const uint8_t* body,size_t n,uint32_t now,bool permit,bool fromUsb){
    WiredPresence& presence=fromUsb?usb_:spi_;
    uint16_t& ack=fromUsb?ackUsb_:ackSpi_;
    if (n==13 && body[0]==5 && !memcmp(body+1,"XIAO235",7) && body[8]==1) {
      bool changed=presence.observe(get32(body+9),seq,now);
      if(changed&&!fromUsb){slowOnly_=false;fastMisses_=slowValid_=0;cooldown_=1000;}
      if (changed && open_ && fromUsb==useUsb_) { resetSession();waitLift_=true;drawPage(lcd); }
      ack=seq;
      return;
    }
    if (fromUsb!=useUsb_ || (fromUsb&&spi_.present())||!open_ || !permit || !enrolled_ || !presence.wanted()) return;
    if (body[0]==0x60 || body[0]==0x62) {
      uint8_t response[57]{};size_t len=0;
      bool was=channel_.established();
      if (!channel_.onRecord(body,n,response,len)||!len||len>sizeof up_) return;
      memcpy(up_,response,len);upLen_=len;ack=seq;
      if (body[0]==0x60 && !proofPending_) {proofPending_=true;proofAt_=now;}
      if (was && !channel_.established()) {pictures.clearView();resetLocalInput();firstPaint_=true;live_=false;state_=0;waitLift_=true;drawPage(lcd);}
      if (!was && channel_.established()) {readySince_=now;proofPending_=false;++handshakes_;presence.seen(now);}
      return;
    }
    uint8_t clear[40];size_t len=0;
    if (!channel_.unwrap(body,n,clear,len) || !len) return;
    presence.seen(now);progressAt_=now;
    uint32_t before=paints_;
    if (len==1 && clear[0]==4) {
      heartbeat_=now;
      if (!live_) { live_=true;waitLift_=true;lcd.fillScreen(TFT_BLACK);bar(lcd); }
    } else if (len==1 && clear[0]==3) {
      live_=false;waitLift_=true;state_=0;resetLocalInput();pictures.clearView();firstPaint_=true;readySince_=now;drawPage(lcd);
    } else if(live_&&clear[0]==8&&len==3){
      uint16_t id=wireddesktop::get16(clear+1);
      if(keys.ack(id)){
        if(id==zoomRequest_){zoomLevel_=nextZoom_;zoomRequest_=0;waitLift_=true;bar(lcd);}
        else if(id==focusRequest_){focusRequest_=0;zoomMenu_=false;keys.shown=true;keys.draw(lcd);waitLift_=true;bar(lcd);}
      }
    } else if(live_&&clear[0]==0x0d&&len==3){
      const auto* e=keys.head();
      if(e&&e->seq==wireddesktop::get16(clear+1)&&(e->opcode==0x24||e->opcode==0x28)){
        bool repaint=keys.shown;keys.discardTyping();focusRequest_=0;focusHint_=true;waitLift_=true;
        if(repaint){lcd.fillRect(0,WiredKeys::Top,480,296-WiredKeys::Top,TFT_BLACK);keys.queue(0x26,0,"",event_);}
        bar(lcd);
      }
    } else if (!live_||!paint(lcd,clear,len)) {resetSession();drawPage(lcd);return;}
    if(firstPaint_&&paints_!=before){firstPaint_=false;bar(lcd);}
    ack=seq;
    if (!ackOrTouch(len==1&&clear[0]==4)) {resetSession();drawPage(lcd);}
  }
  bool paint(TFT_eSPI& lcd,const uint8_t* body,size_t len) {
    using namespace wireddesktop;
    unsigned edge=keys.shown?unsigned(WiredKeys::Top):zoomMenu_?ZoomTop:unsigned(Height);
    if(body[0]==6||body[0]==7||body[0]==9||body[0]==10||body[0]==11)
      return pictures.record(lcd,body,len,edge,pixels_,paints_,commitGuard);
    if(pictures.busy()||len<8)return false;
    uint16_t x=get16(body+1),y=get16(body+3);
    if (x>=Width||y>=Height)return false;
    if (body[0]==1 && len==11) {
      uint16_t w=get16(body+5),h=get16(body+7);
      if (!w || !h || uint32_t(x)+w>Width || uint32_t(y)+h>Height)return false;
      h=WiredPictures::clipped(y,h,edge);if(h){lcd.fillRect(x,y,w,h,get16(body+9));pixels_+=uint32_t(w)*h;++paints_;}return true;
    } else if(body[0]==2 && len==6+2*size_t(body[5]) && body[5] && body[5]<=17 && x+body[5]<=Width) {
      if(y>=edge)return true;
      uint16_t row[17];for(unsigned i=0;i<body[5];++i)row[i]=get16(body+6+2*i);
      lcd.setAddrWindow(x,y,body[5],1);lcd.pushColors(row,body[5],true);pixels_+=body[5];++paints_;return true;
    }
    return false;
  }
};
