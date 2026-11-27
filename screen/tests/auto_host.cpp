#include "AutoWired.h"
#include "XiaoLights.h"
#include <new>
#include <cstring>
#include <algorithm>

int esp_efuse_mac_get_default(uint8_t* data) {
  const uint8_t mac[] = {2,3,4,5,6,7}; memcpy(data,mac,6); return 0;
}
void esp_fill_random(void* data,size_t n) {
  static uint8_t nonce=42;
  auto* p=static_cast<uint8_t*>(data);while(n--) *p++=++nonce;
}

picturestore::Shared picturestore::shared;
static AutoWired viewer;
static TFT_eSPI lcd;
static uint8_t pending[73],req[73];
static bool haveReply=false;
bool wiredDesktopExchange(uint8_t* q,uint8_t* r,size_t n) {
  std::memcpy(req,q,n);
  if(!haveReply) return false;
  std::memcpy(r,pending,n);haveReply=false;return true;
}
bool wiredDesktopTransfer(uint8_t* q,uint8_t* r,size_t n,bool){return wiredDesktopExchange(q,r,n);}
extern "C" {
const char* drawn_status(){return lcd.statusLine.c_str();}
unsigned fast_fallbacks(){return viewer.fastFallbacks;}
unsigned fast_promotions(){return viewer.fastPromotions;}
void light_reply(){
  memset(pending,0,73);memcpy(pending,"DLR1",4);wireddesktop::put16(pending+71,wireddesktop::checksum(pending,71));haveReply=true;
}
unsigned probe_picture_store(){return picturestore::selfTest();}

void clear_all() {viewer.pictures.release();new(&viewer) AutoWired();viewer.pictures.reserve();new(&lcd) TFT_eSPI();fakeNow=10;haveReply=false;}
int enroll(const uint8_t* inner){return viewer.enroll(inner);}
int step(uint32_t ms,bool permit){
  fakeNow+=ms;
  return viewer.step(lcd,10,permit);
}
void step_irq(uint32_t ms,bool low){fakeNow+=ms;viewer.step(lcd,10,true,low);}
unsigned touch_reads(){return lcd.touchReads;}
unsigned bars(){return lcd.bars;}
void warning(){wirednotice::Notice n;n.level=wirednotice::Warning;strcpy(n.text,"Bench advisory");viewer.setNotice(lcd,n);}
void tap(bool down,uint16_t x,uint16_t y){lcd.down=down;lcd.x=x;lcd.y=y;}
void open_view(){viewer.open(lcd);}
void select_view(){viewer.select();}
int flags(){return (viewer.active()?1:0)|(viewer.live()?2:0)|(viewer.canOpen()?4:0)|(viewer.usbActive()?8:0)|
                    (viewer.established()?16:0)|(viewer.dismissed()?32:0);}
unsigned count_paints(){return viewer.paints();}
unsigned color(){return lcd.lastColor;}
unsigned at(unsigned x,unsigned y){return lcd.surface[y*480+x];}
unsigned frames(){return viewer.pictures.frames;}
unsigned tiles(){return viewer.pictures.tiles;}
unsigned decode_fails(){return viewer.pictures.failures;}
unsigned overflows(){return viewer.droppedInputs;}
int keys_visible(){return viewer.keys.shown;}
unsigned key_receipts(){return viewer.keys.accepted;}
unsigned zoom_level(){return viewer.zoomLevel();}
bool zoom_wait(){return viewer.zoomWaiting();}
const char* connection_state(){return wiredentry::message(viewer.connection).label;}
int connection_issue(){return viewer.showIssue();}
void confirm_harness_gap(){viewer.harnessDetached();}
void signal_helper(bool ready,bool silent){viewer.checkPhysicalHelper(ready,silent,fakeNow);}
int auto_entry(bool calibrated,bool touched,bool gesture,unsigned idle,bool sensitive,bool operation,bool guard){
  return wiredentry::mayOpen(calibrated,touched,gesture,idle,sensitive,operation,guard);
}

void send_spi(uint16_t seq,const uint8_t* payload,size_t len,bool crcOk){
  memset(pending,0,73); std::memcpy(pending,"DTR1",4);pending[4]=1;
  wireddesktop::put16(pending+5,seq);wireddesktop::put16(pending+7,len);
  if(len)memcpy(pending+9,payload,len);
  wireddesktop::put16(pending+71,wireddesktop::checksum(pending,71)^!crcOk);
  haveReply=true;
}
int spi_up(uint8_t* out){std::memcpy(out,req+14,req[13]);return req[13];}
int direct(uint16_t seq,const uint8_t* p,size_t n,bool permit,uint8_t* out){
  bool busy=false;uint16_t ack=0;size_t len=0;viewer.usbExchange(lcd,seq,p,n,permit,ack,busy,out,len);
  return (busy?1<<24:0)|(ack<<8)|len;
}
}
