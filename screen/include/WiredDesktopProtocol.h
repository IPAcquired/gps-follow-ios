#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace wireddesktop {
constexpr size_t PacketSize = 73;
// ESP32 Arduino's SPI FIFO reads complete 32-bit words for the final short word.
constexpr size_t BufferSize = (PacketSize + 3) & ~size_t(3);
constexpr uint16_t Width = 480, Height = 296;

inline uint16_t get16(const uint8_t* p) {
  return (uint16_t(p[0]) << 8) | p[1];
}
inline void put16(uint8_t* p, uint16_t value) {
  p[0] = value >> 8;
  p[1] = uint8_t(value);
}
inline uint16_t checksum(const uint8_t* bytes, size_t count) {
  uint16_t crc = 0xffff;
  for (size_t i = 0; i < count; ++i) {
    crc ^= uint16_t(bytes[i]) << 8;
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = crc & 0x8000 ? uint16_t((crc << 1) ^ 0x1021) : uint16_t(crc << 1);
  }
  return crc;
}

struct Touch {
  uint8_t state = 0;
  uint16_t x = 0, y = 0, sequence = 0;
  void set(uint8_t next, uint16_t px, uint16_t py) {
    state = next; x = px; y = py;
    if (++sequence == 0) ++sequence;
  }
};

inline void makeRequest(uint8_t* p, const Touch& t, uint16_t ack) {
  memset(p, 0, PacketSize);
  memcpy(p, "DTQ1", 4); p[4] = t.state;
  put16(p + 5, t.x); put16(p + 7, t.y);
  put16(p + 9, t.sequence); put16(p + 11, ack);
  put16(p + 71, checksum(p, 71));
}

struct Update {
  uint8_t type = 0;
  uint16_t sequence = 0, x = 0, y = 0, w = 0, h = 0, color = 0;
  const uint8_t* pixels = nullptr;
};

// Accept only complete, in-bounds rectangles in the remote viewport.
inline bool decode(const uint8_t* p, Update& out) {
  out = Update{};
  if (memcmp(p, "DTR1", 4) || get16(p + 71) != checksum(p, 71)) return false;
  uint16_t n = get16(p + 7);
  if (p[4] == 0) return n == 0;
  if (p[4] != 1 || n == 0 || n > 62 || get16(p + 5) == 0) return false;
  Update v;
  v.sequence = get16(p + 5); v.type = p[9];
  const uint8_t* body = p + 9;
  if (v.type == 1 && n == 11) {
    v.x = get16(body+1); v.y = get16(body+3); v.w = get16(body+5);
    v.h = get16(body+7); v.color = get16(body+9);
  } else if (v.type == 2 && n >= 8) {
    v.x = get16(body+1); v.y = get16(body+3);
    v.w = body[5]; v.h = 1; v.pixels = body+6;
    if (v.w > 28 || n != 6 + 2*v.w) return false;
  } else if ((v.type == 3 || v.type == 4) && n == 1) {
    out = v; return true;
  } else return false;
  if (!v.w || !v.h || uint32_t(v.x)+v.w > Width || uint32_t(v.y)+v.h > Height)
    return false;
  out = v; return true;
}
}
