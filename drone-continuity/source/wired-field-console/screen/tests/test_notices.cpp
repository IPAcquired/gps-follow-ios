#include "WiredNotices.h"
#include <cassert>
#include <cstring>
#include <cstdio>
using namespace wirednotice;
int main(){
  Tracker t;
  t.observe(Warning,1000,"PreArm: advisory",100);
  assert(!t.hard(101)&&t.current(101).level==Warning);
  t.observe(Warning,1000,"PreArm: advisory",12090);
  assert(t.current(12150).level==None); // A replay cannot refresh the advisory.
  t.observe(Critical,1010,"PreArm: condition A",12500);
  assert(t.hard(12501)&&t.current(12501).level==Critical);
  t.observe(Critical,1010,"PreArm: condition A",21000);
  assert(!t.hard(22501)&&t.current(22501).level==Critical);
  for(unsigned i=1;i<=5;++i){
    uint32_t received=12500+i*30500;
    t.observe(Critical,1010+i*30.5,"PreArm: condition A",received);
    assert(!t.hard(received)&&!strcmp(t.current(received).text,"PreArm: condition A"));
  }
  t.observe(Critical,1163,"Independent condition B",165200);
  assert(t.hard(165201)&&!strcmp(t.current(165201).text,"Independent condition B"));
  t.observe(Emergency,1164,"Immediate condition C",166100);
  assert(t.hard(166110)&&t.current(166110).level==Emergency);
  t.observe(Critical,1161,"PreArm: condition A",175900);
  assert(!t.hard(176150)); // Out-of-order old snapshots never extend priority.
  t.observe(Critical,1270,"PreArm: condition A",274000);
  assert(t.hard(274001)); // A new incident after a quiet interval gets priority.
  Tracker wrap;
  wrap.observe(Error,41,"Sensor fault",0xffffff00u);
  assert(wrap.hard(10u)&&!wrap.hard(11000u));
  puts("PASS advisory, incident deduplication across fresh repeats, persistent critical indication, new event priority, recurrence and clock wrap");
}
