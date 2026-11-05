#pragma once
#include <stdint.h>
#include <math.h>
#include <string.h>

struct FlightView {
  uint32_t received = 0;
  bool connected = false;
  bool armedKnown = false;
  bool armed = false;
  bool groundKnown=false,onGround=false;
  uint32_t groundReceived=0;
  float voltage = NAN;
  float speed = NAN;
  float altitude = NAN;
  double latitude=NAN,longitude=NAN;
  int satellites = -1;
  int fix = -1;
  char mode[25] = "UNKNOWN";
  char notice[100] = "Connect the Pi or PC bridge to receive telemetry";
  char link[40] = "WAITING FOR CONNECTION";
  uint32_t packets = 0;
};

inline bool viewFresh(const FlightView& v, uint32_t now) {
  return v.connected && v.received != 0 && uint32_t(now - v.received) < 3000;
}
inline float boundedNumber(double v, double low, double high) {
  return isfinite(v) && v >= low && v <= high ? float(v) : NAN;
}
inline bool observationFresh(bool declaredFresh, double age, uint32_t received, uint32_t now) {
  return declaredFresh&&isfinite(age)&&age>=0&&age<=3000&&received!=0&&uint32_t(now-received)<5000;
}
inline bool verifiedDronePosition(int fix,bool latitudeFresh,bool longitudeFresh,double latitude,double longitude){
  return fix>=3&&fix<=8&&latitudeFresh&&longitudeFresh&&isfinite(latitude)&&isfinite(longitude)&&latitude>=-90&&latitude<=90&&longitude>=-180&&longitude<=180;
}
inline bool privateAddress(const char* text) {
  unsigned values[4] = {}; int component = 0, digits = 0;
  if (!text || !*text) return false;
  for (const char* p = text; ; ++p) {
    if (*p >= '0' && *p <= '9') {
      if (++digits > 3 || (digits > 1 && values[component] == 0)) return false;
      values[component] = values[component] * 10 + unsigned(*p - '0');
      if (values[component] > 255) return false;
    } else if ((*p == '.' && component < 3) || *p == 0) {
      if (!digits) return false;
      if (!*p) break;
      ++component; digits = 0;
    } else return false;
  }
  return component == 3 && (values[0] == 10 ||
      (values[0] == 172 && values[1] >= 16 && values[1] <= 31) ||
      (values[0] == 192 && values[1] == 168));
}
