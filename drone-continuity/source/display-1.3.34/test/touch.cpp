#include "TouchCalibration.h"
#include <assert.h>
#include <stdio.h>
int main() {
  unsigned checks=0; uint16_t out[5];
  const uint16_t good[][8]={{300,300,300,3700,3700,300,3700,3700},
    {300,300,3700,300,300,3700,3700,3700},
    {3700,3700,300,3700,3700,300,300,300}};
  for(auto& v:good){assert(calibrationFromCorners(v,out));++checks;assert(validCalibration(out));++checks;}
  const uint16_t bad[][8]={{2000,2000,2000,2000,2000,2000,2000,2000},
    {0,0,0,4095,4095,0,4095,4095},{300,300,1800,3700,3700,300,3700,3700},
    {300,300,300,700,700,300,700,700}};
  for(auto& v:bad){assert(!calibrationFromCorners(v,out));++checks;}
  printf("PASS: %u touch-calibration geometry assertions\n",checks);
}
