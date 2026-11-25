#pragma once
#include <stdint.h>

class BootMenuGesture {
 public:
  bool tick(uint32_t now,bool down) {
    if(!down){tracking=used=false;return false;}
    if(!tracking){tracking=true;began=now;}
    if(!used&&uint32_t(now-began)>=1000){used=true;return true;}
    return false;
  }
 private:
  bool tracking=false,used=false;uint32_t began=0;
};

// RAM-only consent: no button, serial command or saved preference can arm sleep.
// A fresh release is mandatory after the owner selects the on-screen option.
class PowerGate {
 public:
  static constexpr uint32_t WINDOW_MS = 15000, HOLD_MS = 3000;
  void prepare(uint32_t now) {
    cancel(); active = true; preparedAt = now;
  }
  void cancel() { active = released = holding = confirmed = false; }
  bool tick(uint32_t now, bool down) {
    if (!active) return false;
    if (uint32_t(now - preparedAt) >= WINDOW_MS) { cancel(); return false; }
    if (!released) { if (!down) released = true; return false; }
    if (confirmed) {
      if (!down) { cancel(); return true; }
      return false;
    }
    if (!down) { holding = false; return false; }
    if (!holding) { holding = true; heldAt = now; }
    if (uint32_t(now - heldAt) >= HOLD_MS) confirmed = true;
    return false; // Sleep only on release, never while wake GPIO is held low.
  }
  bool active = false, released = false, holding = false, confirmed = false;
  uint32_t preparedAt = 0, heldAt = 0;
};
