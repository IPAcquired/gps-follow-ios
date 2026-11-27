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
inline RgbLight lightPattern(uint8_t mode,uint8_t color,uint8_t brightness,uint32_t now,uint8_t beaconPattern=0,uint8_t speed=29){
  const RgbLight palette[]={{255,255,255},{255,0,0},{0,255,0},{0,0,255},{0,255,255},{255,0,255},{255,120,0},{255,65,0},{255,255,0},{75,0,130},{148,0,255}};
  if(mode==0||mode>5)return {0,0,0};
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
  if(mode==3){uint32_t hue=(uint64_t(now)*100/period)%1536,sector=hue/256,step=hue%256;
    switch(sector){case 0:rgb={255,uint8_t(step),0};break;case 1:rgb={uint8_t(255-step),255,0};break;case 2:rgb={0,255,uint8_t(step)};break;case 3:rgb={0,uint8_t(255-step),255};break;case 4:rgb={uint8_t(step),0,255};break;default:rgb={255,0,uint8_t(255-step)};}}
  if(mode==4&&now%period>=(speed>=60?period/2:period*3/10))level=0;
  return {uint8_t(rgb.r*level/255),uint8_t(rgb.g*level/255),uint8_t(rgb.b*level/255)};
}
