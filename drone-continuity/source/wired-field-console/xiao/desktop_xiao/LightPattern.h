#pragma once
#include <stdint.h>
struct RgbLight {uint8_t r,g,b;};
constexpr uint8_t LIGHT_COLOR_COUNT=11;
constexpr uint8_t LIGHT_SPEED_COUNT=100;
inline uint32_t lightPeriod(uint8_t speed){
  static const uint16_t periods[]={10000,9434,8900,8396,7920,7472,7049,6649,6273,5918,5583,5266,4968,4687,4421,4171,3935,3712,3502,3304,3117,2940,2774,2617,2468,2329,2197,2072,1955,1844,1740,1641,1548,1461,1378,1300,1226,1157,1091,1030,971,916,864,815,769,726,685,646,609,575,542,512,483,455,429,405,382,361,340,321,303,286,269,254,240,226,213,201,190,179,169,159,150,142,134,126,119,112,106,100,96,92,88,84,80,76,72,68,64,60,56,52,48,44,40,36,32,28,24};
  if(speed>=100)return 0;
  return periods[(speed<1?1:speed)-1];
}
inline int lightAdjustment(int x){return x<100?-10:x<190?-1:x<290?0:x<390?1:10;}
inline void selectBeacon(uint8_t& mode,uint8_t& pattern){if(mode==4)pattern=(pattern+1)%4;else mode=4;}
// The service samples the rainbow clock at the same 2 ms interval as the LEDs.
// Accumulating elapsed time preserves the visible hue when the speed changes.
inline uint32_t rainbowCycleMs(uint8_t speed) {
  const uint32_t rate = speed >= 100 ? 20 : lightPeriod(speed);
  return 768 + 15 * rate;
}
class RainbowClock {
  uint32_t phase_ = 0, sampled_ = 0, cycle_ = 0;
 public:
  void reset() { phase_ = 0; cycle_ = 0; }
  uint16_t sample(uint32_t now, uint8_t speed) {
    if (cycle_) {
      const uint32_t elapsed = now - sampled_;
      phase_ += uint32_t((uint64_t(elapsed % cycle_) << 32) / cycle_);
    }
    sampled_ = now;
    cycle_ = rainbowCycleMs(speed);
    return uint16_t((uint64_t(phase_) * 1536) >> 32);
  }
};
inline RgbLight rainbowPixel(uint16_t hue, uint8_t brightness) {
  // Smoothstep the changing channel at each primary/secondary colour. One
  // channel always remains at full requested brightness, even at level 1.
  const uint32_t t = hue & 255;
  const uint32_t eased = (t * t * (765 - 2 * t) + 32512) / 65025;
  const uint8_t rise = uint8_t((eased * brightness + 127) / 255);
  const uint8_t fall = uint8_t(brightness - rise);
  switch (hue >> 8) {
    case 0: return {brightness, rise, 0};
    case 1: return {fall, brightness, 0};
    case 2: return {0, brightness, rise};
    case 3: return {0, fall, brightness};
    case 4: return {rise, 0, brightness};
    default: return {brightness, 0, fall};
  }
}
inline RgbLight lightPattern(uint8_t mode,uint8_t color,uint8_t brightness,uint32_t now,uint8_t beaconPattern,uint8_t speed,uint16_t hue){
  const RgbLight palette[]={{255,255,255},{255,0,0},{0,255,0},{0,0,255},{0,255,255},{255,0,255},{255,120,0},{255,65,0},{255,255,0},{75,0,130},{148,0,255}};
  if(mode==0||mode>5)return {0,0,0};
  if(mode==3)return rainbowPixel(hue,brightness);
  if(mode==5)return {brightness,brightness,brightness};
  uint8_t chosen=color%LIGHT_COLOR_COUNT;
  if(speed>=100){RgbLight rgb=palette[chosen];return {uint8_t(rgb.r*brightness/255),uint8_t(rgb.g*brightness/255),uint8_t(rgb.b*brightness/255)};}
  const uint32_t period=lightPeriod(speed);
  if(mode==4){uint32_t pulse=now/period;
    if(beaconPattern==1){const uint8_t rainbow[]={1,7,8,2,3,9,10};chosen=rainbow[pulse%7];}
    else if(beaconPattern==2)chosen=pulse%2?4:6;
    else if(beaconPattern==3&&pulse%2)chosen=0;
  }
  RgbLight rgb=palette[chosen];uint32_t level=brightness;
  if(mode==2){uint32_t phase=now%(period*2);level=uint32_t(brightness)*(phase<period?phase:period*2-phase)/period;}
  if(mode==4&&now%period>=(speed>=60?period/2:period*3/10))level=0;
  return {uint8_t(rgb.r*level/255),uint8_t(rgb.g*level/255),uint8_t(rgb.b*level/255)};
}
