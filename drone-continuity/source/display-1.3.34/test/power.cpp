#include "PowerGate.h"
#include <assert.h>
#include <stdio.h>
int main() {
  unsigned checks=0;
  #define CHECK(v) do { assert(v); ++checks; } while(0)
  PowerGate p;
  BootMenuGesture menu;
  CHECK(!menu.tick(0,true));CHECK(!menu.tick(999,true));CHECK(menu.tick(1000,true));
  CHECK(!menu.tick(9000,true));CHECK(!menu.tick(9001,false));
  CHECK(!menu.tick(10000,true));CHECK(menu.tick(11000,true));CHECK(!p.active);
  for (unsigned t=0;t<60000;t+=10) CHECK(!p.tick(t,true));
  p.prepare(60000);
  CHECK(!p.tick(60000,true)); CHECK(!p.tick(64000,true));
  CHECK(!p.confirmed); // A button already held when menu selected cannot count.
  CHECK(!p.tick(64001,false)); CHECK(p.released);
  CHECK(!p.tick(64010,true)); CHECK(!p.tick(67009,true));
  CHECK(!p.confirmed); CHECK(!p.tick(67010,true)); CHECK(p.confirmed);
  CHECK(!p.tick(67011,true)); CHECK(p.tick(67012,false));
  CHECK(!p.active); CHECK(!p.tick(67013,false));
  p.prepare(70000); p.tick(70001,false); p.tick(70002,true);
  CHECK(!p.tick(72000,false)); CHECK(!p.holding);
  p.tick(72001,true); CHECK(!p.tick(75000,true)); CHECK(!p.confirmed);
  p.cancel(); CHECK(!p.tick(78000,false)); CHECK(!p.active);
  p.prepare(80000); p.tick(80001,false); p.tick(80002,true);
  CHECK(!p.tick(95000,false)); CHECK(!p.active); // Expiry wins over release.
  p.prepare(0xfffffff0); p.tick(0xfffffff1,false); p.tick(0xfffffff2,true);
  CHECK(!p.tick(0xbaa,true)); CHECK(p.confirmed);
  CHECK(p.tick(0xbab,false)); // millis wrap remains safe.
  p.prepare(0xfffffff0); CHECK(!p.tick(0x3a88,false)); CHECK(!p.active);
  p.prepare(100); p.tick(101,false); p.tick(102,true); p.tick(3102,true);
  p.cancel(); CHECK(!p.tick(3103,false)); // Leaving/canceling menu always wins.
  printf("PASS: %u power-gate assertions; no hardware sleep invoked\n",checks);
}
