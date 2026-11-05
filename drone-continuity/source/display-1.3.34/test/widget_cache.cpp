#include "WidgetCache.h"
#include <cassert>
int main(){
  WidgetCache c;
  assert(c.changed(1,10,20,80,16,"LIVE",12));
  for(int i=0;i<10000;++i)assert(!c.changed(1,10,20,80,16,"LIVE",12));
  assert(c.changed(1,10,20,80,16,"UNAVAILABLE",13));
  assert(c.changed(1,10,20,80,16,"",13));
  c.resetKind(1);assert(c.changed(1,10,20,80,16,"",13));
  for(int i=0;i<1000;++i)assert(c.changed(2,i,20,80,16,"row",1));
  c.reset();assert(c.changed(1,10,20,80,16,"",13));
}
