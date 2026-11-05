#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <atomic>
#include "Storage.h"
#include "Audio.h"
#include "StorageFormat.h"
#include <sd_diskio.h>
#include <ff.h>
#include <diskio.h>
#ifdef CARD_PREPARATION_SEED
#include <Preferences.h>
#include <sd_diskio.h>
#include <ff.h>
#include <diskio.h>
#include <mbedtls/sha256.h>
#endif
namespace {
SPIClass cardBus(VSPI);SemaphoreHandle_t cardLock=nullptr;QueueHandle_t records=nullptr;
std::atomic<uint32_t> state{0},capacity{0},written{0},dropped{0};
std::atomic<bool> mountWanted{true},unmountWanted{false};
struct StatusRecord {uint32_t uptime;bool connected,armedKnown,armed;};
char logPath[96]={};uint32_t logBytes=0;
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
void task(void*) {
  for(;;) {
    if(unmountWanted) {
      if(audioPlaying()){vTaskDelay(pdMS_TO_TICKS(20));continue;}
      if(xSemaphoreTake(cardLock,pdMS_TO_TICKS(100))==pdTRUE){state=5;SD.end();cardBus.end();state=4;unmountWanted=false;xQueueReset(records);xSemaphoreGive(cardLock);}
    }
    if(mountWanted.exchange(false)) {
      if(xSemaphoreTake(cardLock,pdMS_TO_TICKS(200))==pdTRUE){if(state!=2)mountCard();xSemaphoreGive(cardLock);}
    }
    StatusRecord item;
    if(xQueueReceive(records,&item,pdMS_TO_TICKS(100))!=pdTRUE)continue;
    if(state!=2||unmountWanted){++dropped;continue;}
    if(xSemaphoreTake(cardLock,pdMS_TO_TICKS(100))!=pdTRUE){++dropped;continue;}
    if(logBytes>=1048576)nextLog();
    File log=SD.open(logPath,FILE_APPEND);
    if(log) {
      // Whitelisted non-secret fields only. No SSID, keys, PIN, tokens or QR data.
      char line[180];int bytes=snprintf(line,sizeof(line),"{\"uptime_ms\":%lu,\"telemetry_fresh\":%s,\"armed_known\":%s,\"armed\":%s,\"authority\":\"display_only\"}\n",
        (unsigned long)item.uptime,item.connected?"true":"false",item.armedKnown?"true":"false",item.armedKnown?(item.armed?"true":"false"):"null");
      if(bytes>0&&bytes<int(sizeof(line))&&log.write(reinterpret_cast<uint8_t*>(line),bytes)==size_t(bytes)){log.flush();logBytes+=bytes;++written;}else{++dropped;state=3;}
      log.close();
    }else{++dropped;state=3;}
    xSemaphoreGive(cardLock);
  }
}
}
void beginStorage() {
  cardLock=xSemaphoreCreateMutex();records=xQueueCreate(8,sizeof(StatusRecord));
  if(!cardLock||!records||xTaskCreatePinnedToCore(task,"display-sd",8192,nullptr,1,nullptr,0)!=pdPASS)state=3;
}
void requestStorageMount(){if(cardLock&&state!=2){unmountWanted=false;mountWanted=true;}}
void requestStorageUnmount(){mountWanted=false;unmountWanted=true;}
bool verifyStorageReadWrite(){
  if(!cardLock||state!=2||unmountWanted||audioPlaying()||xSemaphoreTake(cardLock,pdMS_TO_TICKS(250))!=pdTRUE)return false;
  const char* path="/flight-team/cache/sd-verify-20261022.tmp";
  // Refuse a pre-existing path. Never truncate an unknown file.
  if(state!=2||unmountWanted||SD.exists(path)){xSemaphoreGive(cardLock);return false;}
  uint8_t expected[1024],actual[1024];
  for(size_t i=0;i<sizeof(expected);++i)expected[i]=uint8_t(i*37+19);
  File file=SD.open(path,FILE_WRITE);bool created=bool(file);
  bool ok=created&&file.write(expected,sizeof(expected))==sizeof(expected);
  if(file){file.flush();file.close();}
  file=SD.open(path,FILE_READ);
  ok=ok&&file&&file.size()==sizeof(expected)&&file.read(actual,sizeof(actual))==sizeof(actual)&&memcmp(actual,expected,sizeof(actual))==0;
  if(file)file.close();
  bool removed=created&&SD.remove(path);ok=ok&&removed;
  xSemaphoreGive(cardLock);
  Serial.printf("{\"event\":\"sd_read_write_verified\",\"bytes\":1024,\"passed\":%s,\"temporary_removed\":%s}\n",ok?"true":"false",removed?"true":"false");
  return ok;
}
StorageInfo storageInfo(){StorageInfo info;info.state=state.load();info.capacityMiB=capacity.load();info.records=written.load();info.dropped=dropped.load();return info;}
const char* storageStateName(uint32_t value){static const char* names[]={"NO CARD / NOT MOUNTED","MOUNTING","READY","STORAGE ERROR","SAFELY UNMOUNTED","UNMOUNTING","PREPARING CARD","NTFS: FAT32 REQUIRED","EXFAT: FAT32 REQUIRED"};return value<9?names[value]:"UNKNOWN";}
void recordDisplayStatus(bool connected,bool armedKnown,bool armed){
  if(!records||state!=2||unmountWanted)return;
  StatusRecord record={millis(),connected,armedKnown,armed};if(xQueueSend(records,&record,0)!=pdTRUE)++dropped;
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

#ifdef CARD_PREPARATION_SEED
namespace {
constexpr uint64_t EXPECTED_CARD_BYTES=128177930240ULL;
uint8_t preparedDrive=0xff;
bool probeMatches=false;
uint32_t read32(const uint8_t* p){return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);}
extern "C" {
extern const uint8_t compassStart[] asm("_binary_assets_compass_pcm_start"),compassEnd[] asm("_binary_assets_compass_pcm_end");
extern const uint8_t ekfStart[] asm("_binary_assets_ekf_pcm_start"),ekfEnd[] asm("_binary_assets_ekf_pcm_end");
extern const uint8_t batteryStart[] asm("_binary_assets_battery_pcm_start"),batteryEnd[] asm("_binary_assets_battery_pcm_end");
extern const uint8_t radioStart[] asm("_binary_assets_radio_pcm_start"),radioEnd[] asm("_binary_assets_radio_pcm_end");
extern const uint8_t gpsStart[] asm("_binary_assets_gps_pcm_start"),gpsEnd[] asm("_binary_assets_gps_pcm_end");
extern const uint8_t generalStart[] asm("_binary_assets_general_pcm_start"),generalEnd[] asm("_binary_assets_general_pcm_end");
}
const uint8_t* seedStarts[]={compassStart,ekfStart,batteryStart,radioStart,gpsStart,generalStart};
const uint8_t* seedEnds[]={compassEnd,ekfEnd,batteryEnd,radioEnd,gpsEnd,generalEnd};
void hashHex(const uint8_t* data,size_t size,char out[65]){uint8_t hash[32];mbedtls_sha256_ret(data,size,hash,0);for(int i=0;i<32;++i)snprintf(out+i*2,3,"%02x",hash[i]);}
bool probeLocked() {
  SD.end();cardBus.begin(18,19,23,5);probeMatches=false;
  preparedDrive=sdcard_init(5,&cardBus,20000000);
  if(preparedDrive==0xff)return false;
  if(disk_initialize(preparedDrive)&STA_NOINIT){sdcard_uninit(preparedDrive);preparedDrive=0xff;return false;}
  uint64_t bytes=uint64_t(sdcard_num_sectors(preparedDrive))*sdcard_sector_size(preparedDrive);
  uint8_t sector[512];bool ok=bytes==EXPECTED_CARD_BYTES&&sd_read_raw(preparedDrive,sector,0);
  if(ok&&memcmp(sector+3,"NTFS    ",8)!=0) {
    // Only accept the first NTFS primary partition, never Linux or H743 FAT logs.
    uint32_t start=read32(sector+454);
    ok=sector[510]==0x55&&sector[511]==0xaa&&sector[450]==0x07&&start>=2048&&
       uint64_t(start)*512<bytes&&sd_read_raw(preparedDrive,sector,start);
  }
  ok=ok&&memcmp(sector+3,"NTFS    ",8)==0;
  Serial.printf("{\"event\":\"sd_readonly_probe\",\"bytes\":%llu,\"expected_size\":%s,\"fresh_ntfs_signature\":%s,\"writes\":0}\n",bytes,bytes==EXPECTED_CARD_BYTES?"true":"false",ok?"true":"false");
  probeMatches=ok;
  return ok;
}
}
bool probeFreshCard() {
  if(!cardLock||audioPlaying()||state==2||xSemaphoreTake(cardLock,pdMS_TO_TICKS(200))!=pdTRUE)return false;
  bool ok=probeLocked();
  if(preparedDrive!=0xff){sdcard_uninit(preparedDrive);preparedDrive=0xff;}
  xSemaphoreGive(cardLock);return ok;
}
bool prepareFreshCard() {
  if(!cardLock||audioPlaying()||state==2||xSemaphoreTake(cardLock,pdMS_TO_TICKS(200))!=pdTRUE)return false;
  Preferences consent;consent.begin("displaycard",false);
  if(consent.getBool("attempted",false)||!probeLocked()) {
    if(preparedDrive!=0xff){sdcard_uninit(preparedDrive);preparedDrive=0xff;}
    consent.end();xSemaphoreGive(cardLock);return false;
  }
  // Durable one-use fuse precedes the FIRST data write. A failed attempt needs
  // review; neither normal boot nor the final firmware can repeat formatting.
  if(consent.putBool("attempted",true)!=1){sdcard_uninit(preparedDrive);preparedDrive=0xff;consent.end();xSemaphoreGive(cardLock);return false;}
  state=6;Serial.println("{\"event\":\"sd_format_started\",\"filesystem\":\"FAT32\",\"cluster_bytes\":32768}");
  uint8_t* work=static_cast<uint8_t*>(malloc(4096));char drive[3]={char('0'+preparedDrive),':',0};
  FRESULT result=work?f_mkfs(drive,FM_FAT32,32768,work,4096):FR_NOT_ENOUGH_CORE;
  free(work);sdcard_uninit(preparedDrive);preparedDrive=0xff;
  bool ok=result==FR_OK;
  if(ok)ok=mountCard();
  if(ok)state=6; // Seeding is not yet a ready/mountable storage transaction.
  if(ok){
    uint8_t sector[512];ok=SD.readRAW(sector,0);
    bool mbr=ok&&(sector[450]==0x0b||sector[450]==0x0c);uint32_t start=mbr?read32(sector+454):0;
    if(mbr)ok=SD.readRAW(sector,start);
    bool fat32=ok&&sector[11]==0&&sector[12]==2&&sector[13]==64&&sector[17]==0&&sector[18]==0&&read32(sector+36)>0&&memcmp(sector+82,"FAT32   ",8)==0;
    ok=ok&&mbr&&fat32;
    Serial.printf("{\"event\":\"sd_filesystem_readback\",\"mbr\":%s,\"fat32\":%s,\"cluster_bytes\":%u,\"partition_start_sector\":%lu,\"passed\":%s}\n",mbr?"true":"false",fat32?"true":"false",unsigned(sector[13])*512,(unsigned long)start,ok?"true":"false");
  }
  const char* names[]={"compass","ekf","battery","radio","gps","general"};
  for(int i=0;i<6&&ok;++i) {
    String path=String("/flight-team/audio/")+names[i]+".pcm";size_t size=seedEnds[i]-seedStarts[i];
    File file=SD.open(path,FILE_WRITE);ok=file&&file.write(seedStarts[i],size)==size;if(file){file.flush();file.close();}
    uint8_t expected[32],actual[32],buffer[256];mbedtls_sha256_ret(seedStarts[i],size,expected,0);
    mbedtls_sha256_context hash;mbedtls_sha256_init(&hash);mbedtls_sha256_starts_ret(&hash,0);
    file=SD.open(path,FILE_READ);size_t read=0;
    while(file&&file.available()){int count=file.read(buffer,sizeof(buffer));if(count<=0)break;mbedtls_sha256_update_ret(&hash,buffer,count);read+=count;delay(1);}
    if(file)file.close();mbedtls_sha256_finish_ret(&hash,actual);mbedtls_sha256_free(&hash);
    ok=ok&&read==size&&memcmp(expected,actual,32)==0;
    char hex[65];hashHex(seedStarts[i],size,hex);
    Serial.printf("{\"event\":\"sd_asset_verified\",\"asset\":\"%s.pcm\",\"bytes\":%u,\"sha256\":\"%s\",\"passed\":%s}\n",names[i],unsigned(size),hex,ok?"true":"false");
  }
  if(ok) {
    // Bounded data-path check, not a full-capacity or SD endurance certification.
    uint8_t buffer[1024];uint32_t started=millis(),writeMs=0,readMs=0;
    File test=SD.open("/flight-team/cache/preparation-check.tmp",FILE_WRITE);
    ok=bool(test);
    for(uint32_t block=0;block<1024&&ok;++block){
      for(size_t i=0;i<sizeof(buffer);++i)buffer[i]=uint8_t((block*37+i*13)^(block>>3));
      ok=test.write(buffer,sizeof(buffer))==sizeof(buffer);delay(1);
    }
    if(test){test.flush();test.close();}writeMs=millis()-started;started=millis();
    test=SD.open("/flight-team/cache/preparation-check.tmp",FILE_READ);ok=ok&&test&&test.size()==1048576;
    for(uint32_t block=0;block<1024&&ok;++block){
      ok=test.read(buffer,sizeof(buffer))==int(sizeof(buffer));
      for(size_t i=0;i<sizeof(buffer)&&ok;++i)ok=buffer[i]==uint8_t((block*37+i*13)^(block>>3));
      delay(1);
    }
    if(test)test.close();readMs=millis()-started;
    bool removed=SD.remove("/flight-team/cache/preparation-check.tmp");ok=ok&&removed;
    Serial.printf("{\"event\":\"sd_data_path_test\",\"bytes\":1048576,\"write_ms\":%lu,\"read_ms\":%lu,\"passed\":%s,\"temporary_removed\":%s}\n",(unsigned long)writeMs,(unsigned long)readMs,ok?"true":"false",removed?"true":"false");
  }
  File manifest=ok?SD.open("/flight-team/CARD-INFO.txt",FILE_WRITE):File();
  if(manifest){manifest.print("Flight Team display data. FAT32; voices, logs, profiles and exports only. No secrets or executable files. PC backup: Display-SD-Prepared-20261021.\n");manifest.flush();manifest.close();}
  else ok=false;
  consent.putBool("success",ok);consent.end();state=ok?2:3;
  Serial.printf("{\"event\":\"sd_prepare_complete\",\"passed\":%s,\"format_result\":%u,\"bytes\":%llu,\"files_verified\":%u}\n",ok?"true":"false",unsigned(result),EXPECTED_CARD_BYTES,ok?6:0);
  xSemaphoreGive(cardLock);return ok;
}
bool startFreshCardPreparation(){
  static std::atomic<bool> launched{false};
  if(launched.exchange(true))return false;
  return xTaskCreatePinnedToCore([](void*){bool ok=prepareFreshCard();if(!ok)Serial.println("{\"event\":\"sd_preparation_stopped_review_required\"}");vTaskDelete(nullptr);},"card-prepare",8192,nullptr,0,nullptr,0)==pdPASS;
}
#endif
