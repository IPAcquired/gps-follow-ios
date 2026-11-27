#pragma once
#include <stdint.h>
struct AiUiState {
  enum Phase:uint8_t {Idle,Waiting,Reply,Failed};
  Phase phase=Idle;
  void disconnected(){if(phase==Waiting)phase=Failed;}
  const char* label(bool connected) const {
    if(!connected)return "PI OFFLINE / RECONNECTING";
    switch(phase){case Idle:return "PI CONNECTED / CHOOSE A REQUEST";
      case Waiting:return "PI CONNECTED / WAITING FOR REPLY";
      case Reply:return "PI CONNECTED / ADVISORY RESPONSE";
      default:return "PI CONNECTED / RESPONSE UNAVAILABLE";}
  }
};
