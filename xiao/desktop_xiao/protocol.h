#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace desktop {
constexpr size_t FRAME = 73;
constexpr size_t BODY = 71;
constexpr size_t PAYLOAD = 62;
constexpr size_t WIDTH = 480, HEIGHT = 296; // remaining 24 rows belong to local controls

inline uint16_t read16(const uint8_t *p) { return uint16_t(p[0] << 8) | p[1]; }
inline void write16(uint8_t *p, uint16_t v) { p[0] = v >> 8; p[1] = uint8_t(v); }
inline uint16_t crc(const uint8_t *p, size_t len) {
  uint16_t r = 0xffff;
  while (len--) {
    r ^= uint16_t(*p++) << 8;
    for (unsigned i = 0; i < 8; ++i)
      r = r & 0x8000 ? uint16_t((r << 1) ^ 0x1021) : uint16_t(r << 1);
  }
  return r;
}

struct Slot {
  uint16_t seq = 0;
  uint8_t length = 0;
  uint8_t data[PAYLOAD]{};
  bool offered = false;
};

struct Request {
  uint16_t ack, event, x, y;
  uint8_t action;
  uint8_t upLength = 0;
  uint8_t up[57]{};
};

inline bool parse(const uint8_t *p, Request &q) {
  if (memcmp(p, "DTQ1", 4) != 0 || read16(p + BODY) != crc(p, BODY)) return false;
  const uint8_t length=p[13];
  if(length>57 || (length && p[4]!=0)) return false;
  for(size_t i=14+length;i<BODY;++i) if(p[i]) return false;
  q = {read16(p + 11), read16(p + 9), read16(p + 5), read16(p + 7), p[4]};
  q.upLength=length;
  if(length) memcpy(q.up,p+14,length);
  return q.action == 0 || (q.action <= 2 && q.x < WIDTH && q.y < HEIGHT);
}

inline void reply(uint8_t *p, const Slot &s) {
  memset(p, 0, FRAME);
  memcpy(p, "DTR1", 4);
  if (s.seq) {
    p[4] = 1;
    write16(p + 5, s.seq);
    write16(p + 7, s.length);
    memcpy(p + 9, s.data, s.length);
  }
  write16(p + BODY, crc(p, BODY));
}

// A full-duplex request describes what the screen accepted BEFORE this transfer.
inline bool confirmed(Slot &s, uint16_t sent, uint16_t ack) {
  if (!s.seq || sent != s.seq) return false;
  if (s.offered && s.seq == ack) return true;
  s.offered = true;
  return false;
}
}
