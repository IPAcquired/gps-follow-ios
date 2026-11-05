#include "DisplayBattery.h"
#include <cassert>
#include <iostream>
int main(){
 assert(isnan(displayBatteryVolts(0)));assert(isnan(displayBatteryVolts(4095)));
 assert(displayBatteryEstimate(NAN)==-1);assert(displayBatteryEstimate(0)==-1);
 assert(fabs(displayBatteryVolts(1850)-3.7f)<0.001f);
 assert(displayBatteryFresh(1000,3999,3.7f));assert(!displayBatteryFresh(1000,4000,3.7f));
 assert(!displayBatteryFresh(0,10,3.7f));assert(!displayBatteryFresh(100,101,NAN));
 assert(!displayBatteryFresh(100,101,0));assert(!displayBatteryFresh(100,101,4.5f));
 assert(displayBatteryFresh(UINT32_MAX-100,100,3.7f));
 int last=-1;
 for(int i=0;i<10000;++i){float v=2.5f+i*(1.85f/10000);int p=displayBatteryEstimate(v);assert(p>=last&&p<=100);last=p;}
 assert(displayBatteryEstimate(4.2f)==100);std::cout<<"10000 monotonic battery estimates; invalid readings remain unknown\n";
}
