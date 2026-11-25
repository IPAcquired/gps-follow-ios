#include <Arduino.h>
#include <driver/i2s.h>
#include <atomic>
#include "Audio.h"
#include "Storage.h"
namespace {
QueueHandle_t clips=nullptr;
std::atomic<bool> muted{false},busy{false};
bool ready=false;
struct Clip {uint8_t kind;uint32_t created;};
void task(void*) {
  for(;;) {
    Clip queued;if(xQueueReceive(clips,&queued,portMAX_DELAY)!=pdTRUE||muted||uint32_t(millis()-queued.created)>4000)continue;
    uint8_t clip=queued.kind;
    busy=true;digitalWrite(4,LOW);
    uint16_t samples[128];uint8_t source[128];File file;
    bool voice=clip&&openVoiceClip(clip,file);
    size_t length=voice?size_t(file.size()):4800;
    for(size_t offset=0;offset<length&&!muted;offset+=128) {
      size_t count=min(size_t(128),length-offset);
      if(voice&&readVoiceClip(file,source,count)!=int(count))break;
      for(size_t i=0;i<count;++i) {
        int value;
        if(voice)value=int(source[i])-128;
        else {
          size_t n=offset+i;unsigned note=n/1200;
          float envelope=min(1.0f,float(n%1200)/100)*min(1.0f,float(1200-n%1200)/180);
          value=int(45.0f*envelope*sinf(6.2831853f*((clip?250.0f+clip*50:440.0f)+note*220.0f)*n/8000.0f));
        }
        samples[i]=uint16_t(128+value/3)<<8; // Conservative fixed gain.
      }
      size_t written=0;
      if(i2s_write(I2S_NUM_0,samples,count*sizeof(uint16_t),&written,pdMS_TO_TICKS(100))!=ESP_OK||written!=count*sizeof(uint16_t))break;
    }
    closeVoiceClip(file);
    // DMA drain is bounded; audio never blocks the screen/UI task.
    vTaskDelay(pdMS_TO_TICKS(70));digitalWrite(4,HIGH);busy=false;
    i2s_zero_dma_buffer(I2S_NUM_0);
  }
}
}
bool beginAudio(bool mute) {
  muted=mute;
  i2s_config_t config={};config.mode=i2s_mode_t(I2S_MODE_MASTER|I2S_MODE_TX|I2S_MODE_DAC_BUILT_IN);
  config.sample_rate=8000;config.bits_per_sample=I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format=I2S_CHANNEL_FMT_ONLY_LEFT;config.communication_format=I2S_COMM_FORMAT_STAND_MSB;
  config.dma_buf_count=4;config.dma_buf_len=128;config.tx_desc_auto_clear=true;
  if(i2s_driver_install(I2S_NUM_0,&config,0,nullptr)!=ESP_OK)return false;
  if(i2s_set_dac_mode(I2S_DAC_CHANNEL_LEFT_EN)!=ESP_OK){i2s_driver_uninstall(I2S_NUM_0);return false;}
  clips=xQueueCreate(3,sizeof(Clip));
  if(!clips||xTaskCreatePinnedToCore(task,"display-audio",3072,nullptr,1,nullptr,0)!=pdPASS){i2s_driver_uninstall(I2S_NUM_0);return false;}
  ready=true;queueAudio(0);return true;
}
void setAudioMute(bool mute){muted=mute;if(mute){digitalWrite(4,HIGH);if(clips)xQueueReset(clips);}}
bool audioMuted(){return muted;}
bool audioPlaying(){return busy;}
void queueAudio(uint8_t kind){if(ready&&!muted&&kind<=6){Clip clip={kind,millis()};xQueueSend(clips,&clip,0);}}
void stopAudio(){setAudioMute(true);}
