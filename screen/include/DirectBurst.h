#pragma once
#include <stddef.h>
#include <stdint.h>

// An outer USB frame contains up to eight already authenticated-channel records.
// Decode the complete envelope before handing any bytes to the viewer.
class DirectBurst {
 public:
  static constexpr unsigned Limit = 8;
  bool active() const { return next < count; }
  bool start(uint32_t id, uint16_t first, const char* hex, size_t length) {
    count = next = 0;
    if (!id || !first || !hex || !length || length > Limit * 124 || length % 2) return false;
    size_t offset = 0;
    unsigned used = 0;
    while (offset < length) {
      if (used == Limit) return false;
      int bytes = byte(hex + offset);
      offset += 2;
      if (bytes < 22 || bytes > 61 || size_t(bytes) * 2 > length - offset) return false;
      sizes[used] = bytes;
      for (int pos = 0; pos < bytes; ++pos, offset += 2) {
        int value = byte(hex + offset);
        if (value < 0) return false;
        records[used][pos] = value;
      }
      if (records[used][0] != 0x63) return false;
      ++used;
    }
    request = id; sequence = first; count = used;
    return active();
  }
  void advance() { ++next; sequence = sequence == 65535 ? 1 : sequence + 1; }
  void clear() { count = next = 0; }
  uint32_t request = 0;
  uint16_t sequence = 0;
  unsigned next = 0, count = 0;
  uint8_t records[Limit][61]{}, sizes[Limit]{};
 private:
  static int nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  }
  static int byte(const char* hex) {
    int high = nibble(hex[0]), low = nibble(hex[1]);
    return high < 0 || low < 0 ? -1 : high * 16 + low;
  }
};
