#include "StatusBar.h"
#include <cassert>
#include <limits>
int main(){
 assert(signalBar(true,-60)==BarQuality::Good);assert(signalBar(true,-61)==BarQuality::Medium);
 assert(signalBar(true,-70)==BarQuality::Medium);assert(signalBar(true,-71)==BarQuality::Weak);
 assert(signalBar(true,-80)==BarQuality::Weak);assert(signalBar(true,-81)==BarQuality::Poor);
 assert(signalBar(false,-40)==BarQuality::Unavailable);assert(signalBar(true,0)==BarQuality::Unavailable);
 assert(freshnessBar(true,499,1000)==BarQuality::Good);assert(freshnessBar(true,500,1000)==BarQuality::Medium);
 assert(freshnessBar(true,700,1000)==BarQuality::Weak);assert(freshnessBar(true,900,1000)==BarQuality::Poor);
 assert(freshnessBar(true,1000,1000)==BarQuality::Unavailable);
 assert(freshnessBar(false,0,1000)==BarQuality::Unavailable);assert(freshnessBar(true,0,0)==BarQuality::Unavailable);
 assert(freshnessBar(true,uint64_t(UINT32_MAX)+5,5000)==BarQuality::Unavailable);
 assert(barRgb565(BarQuality::Unavailable,0,123)==0xF800);assert(barRgb565(BarQuality::Unavailable,500,123)==123);
 for(unsigned i=0;i<10000;++i){auto q=freshnessBar(true,i,3000);assert(i<3000||q==BarQuality::Unavailable);assert(worseBar(q,BarQuality::Unavailable)==BarQuality::Unavailable);assert(barRgb565(BarQuality::Good,i,123)==0x07E0);}
}
