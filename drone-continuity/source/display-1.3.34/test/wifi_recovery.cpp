#include <cassert>
#include <stdint.h>
#include "WifiRecovery.h"
int main() {
  WifiRecovery state;
  assert(!state.observe(0,true,0));
  assert(!state.observe(2999,true,0));
  assert(state.observe(3000,true,0));
  assert(!state.observe(3001,true,0));
  assert(!state.observe(17000,true,0));
  assert(state.observe(18000,true,0));
  for(uint32_t i=18001;i<30000;i++) assert(!state.observe(i,true,-119));
  assert(!state.observe(31000,true,0));
  assert(!state.observe(33000,false,0));
  assert(!state.observe(34000,true,0));
  assert(state.observe(37000,true,0));
  WifiRecovery wrap;
  assert(!wrap.observe(UINT32_MAX-1000,true,0));
  assert(wrap.observe(2000,true,0));
}
