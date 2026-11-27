#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <atomic>
#include <fcntl.h>
#include <unistd.h>
#include "Storage.h"
#include "Audio.h"
#include "StorageFormat.h"
#include <sd_diskio.h>
#include <ff.h>
#include <diskio.h>
namespace {
SPIClass cardBus(VSPI);SemaphoreHandle_t cardLock=nullptr;QueueHandle_t records=nullptr;
std::atomic<uint32_t> state{0},capacity{0},written{0},dropped{0},writeErrors{0},sampleSequence{0},producers{0};
std::atomic<bool> mountWanted{true},unmountWanted{false};
std::atomic<bool> verifyWanted{false};
std::atomic<uint32_t> verifyTicket{0};
char logPath[96]={};uint32_t logBytes=0;
int logFd=-1;
unsigned pending=0;
uint32_t flushedAt=0;
void nextLog() {
  snprintf(logPath,sizeof(logPath),"/flight-team/logs/boot-%08lx%08lx.jsonl",(unsigned long)esp_random(),(unsigned long)esp_random());logBytes=0;
}
bool mountCard() {
  state=1;
  capacity=0;
  cardBus.begin(18,19,23,5); // Manufacturer E32R35T manual, page 4. LCD uses HSPI instead.
  if(!SD.begin(5,cardBus,20000000,"/sd",5,false)||SD.cardType()==CARD_NONE){
    SD.end();state=0;
    // FAT mount failure does not imply an absent card. Read the filesystem
    // signature through the same bus, then release the raw driver for rescan.
    uint8_t drive=sdcard_init(5,&cardBus,20000000);
    if(drive!=0xff){
      if(!(disk_initialize(drive)&STA_NOINIT)){
        uint64_t sectors=sdcard_num_sectors(drive);
        capacity=sectors*sdcard_sector_size(drive)/1048576;
        uint8_t sector[512];
        if(sd_read_raw(drive,sector,0)){
          uint32_t format=unsupportedStorageFormat(sector);
          uint32_t start=firstStoragePartition(sector,sectors);
          if(!format&&start&&sd_read_raw(drive,sector,start))format=unsupportedStorageFormat(sector);
          state=format?format:3;
        }else state=3;
      }
      sdcard_uninit(drive);
    }
    Serial.printf("{\"event\":\"sd_mount_failed\",\"state\":\"%s\",\"capacity_mib\":%lu,\"writes\":0}\n",storageStateName(state.load()),(unsigned long)capacity.load());
    return false;
  }
  const char* dirs[]={"/flight-team","/flight-team/audio","/flight-team/logs","/flight-team/exports","/flight-team/profiles","/flight-team/cache"};
  for(auto path:dirs)if(!SD.exists(path)&&!SD.mkdir(path)){SD.end();state=3;return false;}
  capacity=SD.cardSize()/1048576;nextLog();state=2;return true;
}
void loseLog(unsigned extra=0){
  ++writeErrors;dropped.fetch_add(pending+extra);pending=0;state=3;
  if(logFd>=0){::close(logFd);logFd=-1;}
}
bool syncLog(bool finish){
  if(logFd<0)return true;
  if(pending&&::fsync(logFd)!=0){loseLog();return false;}
  written.fetch_add(pending);pending=0;flushedAt=millis();
  if(finish){int result=::close(logFd);logFd=-1;if(result){loseLog();return false;}}
  return true;
}
void appendSample(const FieldSample& item){
  if(logBytes>=1048576){if(!syncLog(true)){++dropped;return;}nextLog();}
  if(logFd<0){
    char path[108];snprintf(path,sizeof path,"/sd%s",logPath);
    logFd=::open(path,O_WRONLY|O_CREAT|O_EXCL,0600);
    if(logFd<0){loseLog(1);return;}
    flushedAt=millis();
  }
  char line[384];int bytes=formatFieldSample(item,line,sizeof line);
  if(bytes<=0||bytes>=int(sizeof line)||::write(logFd,line,bytes)!=bytes){loseLog(1);return;}
  logBytes+=bytes;++pending;
  if(pending>=8||uint32_t(millis()-flushedAt)>=2000)syncLog(false);
}
void task(void*) {
  for(;;) {
    if(mountWanted.exchange(false)) {
      if(xSemaphoreTake(cardLock,pdMS_TO_TICKS(100))==pdTRUE){if(state!=2&&!unmountWanted)mountCard();xSemaphoreGive(cardLock);}
      else if(!unmountWanted)mountWanted=true;
    }
    FieldSample item;
    if(verifyWanted.load(std::memory_order_acquire)){
      const auto id=verifyTicket.load();bool ok=verifyStorageReadWrite();
      Serial.printf("{\"event\":\"sd_check_result\",\"request_id\":%u,\"accepted\":%s}\n",id,ok?"true":"false");
      verifyWanted.store(false,std::memory_order_release);
    }
    if(xQueueReceive(records,&item,pdMS_TO_TICKS(25))==pdTRUE){
      if(state!=2){++dropped;continue;}
      if(xSemaphoreTake(cardLock,pdMS_TO_TICKS(100))!=pdTRUE){++dropped;continue;}
      appendSample(item);xSemaphoreGive(cardLock);
      continue;
    }
    if(unmountWanted&&!audioPlaying()&&!producers.load()&&!uxQueueMessagesWaiting(records)){
      if(xSemaphoreTake(cardLock,pdMS_TO_TICKS(100))==pdTRUE){
        state=5;bool ok=syncLog(true);SD.end();cardBus.end();state=ok?4:3;
        unmountWanted=false;xSemaphoreGive(cardLock);
      }
    }else if(pending&&uint32_t(millis()-flushedAt)>=2000&&xSemaphoreTake(cardLock,0)==pdTRUE){
      syncLog(false);xSemaphoreGive(cardLock);
    }
  }
}
}
void beginStorage() {
  digitalWrite(21,HIGH);pinMode(21,OUTPUT);
  cardLock=xSemaphoreCreateMutex();records=xQueueCreate(12,sizeof(FieldSample));
  if(!cardLock||!records||xTaskCreatePinnedToCore(task,"display-sd",8192,nullptr,1,nullptr,0)!=pdPASS)state=3;
}
bool wiredDesktopTransfer(uint8_t* request,uint8_t* reply,size_t count,bool fast) {
  if (!cardLock || xSemaphoreTake(cardLock, 0) != pdTRUE) return false;
  static uint32_t releasedAt=0;
  if(releasedAt&&uint32_t(micros()-releasedAt)<300){xSemaphoreGive(cardLock);return false;}
  // Mount and safe-unmount use this same object and mutex. begin() is idempotent.
  cardBus.begin(18,19,23,5);
  digitalWrite(5,HIGH);pinMode(5,OUTPUT);
  cardBus.beginTransaction(SPISettings(fast?500000:100000,MSBFIRST,SPI_MODE1));
  digitalWrite(21,LOW);
  delayMicroseconds(10);
  cardBus.transferBytes(request,reply,count);
  delayMicroseconds(10);
  digitalWrite(21,HIGH);
  cardBus.endTransaction();releasedAt=micros();
  xSemaphoreGive(cardLock);
  return true;
}
bool wiredDesktopExchange(uint8_t* q,uint8_t* r,size_t n){return wiredDesktopTransfer(q,r,n,false);}
void requestStorageMount(){if(cardLock&&state!=2){unmountWanted=false;mountWanted=true;}}
void requestStorageUnmount(){mountWanted=false;unmountWanted=true;}
bool requestStorageCheck(uint32_t id){
  if(!records||verifyWanted.load(std::memory_order_acquire))return false;
  verifyTicket.store(id);verifyWanted.store(true,std::memory_order_release);return true;
}
bool verifyStorageReadWrite(){
  if(!cardLock||state!=2||unmountWanted||audioPlaying()||xSemaphoreTake(cardLock,pdMS_TO_TICKS(250))!=pdTRUE)return false;
  char path[86];snprintf(path,sizeof path,"/sd/flight-team/logs/check-%08lx.tmp",(unsigned long)esp_random());
  // O_EXCL binds cleanup to the file we actually created. Existing names survive retries.
  int fd=(state==2&&!unmountWanted)?open(path,O_CREAT|O_EXCL|O_RDWR,0600):-1;
  bool created=fd>=0,ok=created;
  uint8_t chunk[64];constexpr size_t length=1024;
  for(size_t pos=0;ok&&pos<length;pos+=sizeof chunk){
    for(size_t i=0;i<sizeof chunk;i++)chunk[i]=uint8_t((pos+i)*37+19);
    ok=::write(fd,chunk,sizeof chunk)==ssize_t(sizeof chunk);
  }
  if(ok)ok=::fsync(fd)==0&&::lseek(fd,0,SEEK_SET)==0;
  for(size_t pos=0;ok&&pos<length;pos+=sizeof chunk){
    ok=::read(fd,chunk,sizeof chunk)==ssize_t(sizeof chunk);
    for(size_t i=0;ok&&i<sizeof chunk;i++)ok=chunk[i]==uint8_t((pos+i)*37+19);
  }
  if(created&&::close(fd))ok=false;
  bool removed=created&&::unlink(path)==0;ok=ok&&removed;
  xSemaphoreGive(cardLock);
  Serial.printf("{\"event\":\"sd_read_write_verified\",\"bytes\":1024,\"passed\":%s,\"temporary_removed\":%s}\n",ok?"true":"false",removed?"true":"false");
  return ok;
}
StorageInfo storageInfo(){StorageInfo info;info.state=state.load();info.capacityMiB=capacity.load();info.records=written.load();info.dropped=dropped.load();info.errors=writeErrors.load();return info;}
const char* storageStateName(uint32_t value){static const char* names[]={"NO CARD / NOT MOUNTED","MOUNTING","READY","STORAGE ERROR","SAFELY UNMOUNTED","UNMOUNTING","PREPARING CARD","NTFS: FAT32 REQUIRED","EXFAT: FAT32 REQUIRED"};return value<9?names[value]:"UNKNOWN";}
void recordFieldSample(FieldSample sample){
  sample.sequence=sampleSequence.fetch_add(1)+1;
  ++producers;
  if(!records||state!=2||unmountWanted||xQueueSend(records,&sample,0)!=pdTRUE)++dropped;
  --producers;
}
bool openVoiceClip(uint8_t kind,File& file) {
  if(kind<1||kind>6||state!=2||unmountWanted||!cardLock)return false;
  const char* names[]={"compass","ekf","battery","radio","gps","general"};
  if(xSemaphoreTake(cardLock,pdMS_TO_TICKS(100))!=pdTRUE)return false;
  if(state!=2||unmountWanted){xSemaphoreGive(cardLock);return false;}
  String path=String("/flight-team/audio/")+names[kind-1]+".pcm";file=SD.open(path,FILE_READ);
  bool ok=file&&file.size()>=1000&&file.size()<=32000;if(!ok&&file)file.close();xSemaphoreGive(cardLock);return ok;
}
int readVoiceClip(File& file,uint8_t* buffer,size_t size){
  if(!file||!cardLock||xSemaphoreTake(cardLock,pdMS_TO_TICKS(100))!=pdTRUE)return -1;
  int result=file.read(buffer,size);xSemaphoreGive(cardLock);return result;
}
void closeVoiceClip(File& file){if(file&&cardLock&&xSemaphoreTake(cardLock,pdMS_TO_TICKS(200))==pdTRUE){file.close();xSemaphoreGive(cardLock);}}

