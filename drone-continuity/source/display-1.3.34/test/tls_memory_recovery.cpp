#include <cassert>
#include "TlsMemoryRecovery.h"
int main(){
 TlsMemoryRecovery p;
 assert(!p.failure(-0x7F00,0,1000,0));
 assert(!p.failure(-0x7F00,3000,1003,0));
 assert(p.failure(-0x7F00,6000,1006,0));
 assert(!p.failure(-0x7F00,9000,1009,1006));
 assert(!p.failure(-0x7F00,10000,900,1006));
 assert(p.failure(-0x7F00,306000,1306,1006));
 p.success();assert(!p.failure(-0x7F00,307000,1307,1006));
 assert(!p.failure(-0x2700,310000,1310,1006));
 assert(!p.failure(-0x7F00,315000,1315,1006));
 assert(!p.failure(-0x7F00,319000,1319,1006));
 assert(p.failure(-0x7F00,320000,1320,1006));
}
