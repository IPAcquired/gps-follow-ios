#pragma once
#include <math.h>
#include <stdint.h>
// E32R35T: GPIO34, R2/R3 = 100k/100k. Voltage is measured;
// charge is only a coarse 1-cell Li-ion voltage estimate, never a fuel gauge.
inline float displayBatteryVolts(unsigned adcMillivolts) {
  float v=adcMillivolts*0.002f;
  return v>=2.5f&&v<=4.35f?v:NAN;
}
inline bool displayBatteryFresh(uint32_t sampled,uint32_t now,float volts){
  return sampled&&uint32_t(now-sampled)<3000&&isfinite(volts)&&volts>=2.5f&&volts<=4.35f;
}
inline int displayBatteryEstimate(float v) {
  if(!isfinite(v)||v<2.5f||v>4.35f)return -1;
  const float volts[]={3.2f,3.5f,3.65f,3.75f,3.85f,4.0f,4.2f};
  const int percent[]={0,10,20,40,60,80,100};
  if(v<=volts[0])return 0;
  for(int i=1;i<7;++i)if(v<volts[i])return percent[i-1]+int((v-volts[i-1])*(percent[i]-percent[i-1])/(volts[i]-volts[i-1]));
  return 100;
}
