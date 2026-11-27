#pragma once
#include <stdint.h>

// All boundaries are exclusive. The local bar always owns the final 24 rows.
struct WiredLayout {
  bool portrait = false;
  unsigned width() const { return portrait ? 320 : 480; }
  unsigned height() const { return portrait ? 456 : 296; }
  unsigned keysTop() const { return height() - 144; }
  unsigned zoomTop() const { return height() - 76; }
  unsigned backEnd() const { return portrait ? 56 : 84; }
  unsigned zoomStart() const { return portrait ? 186 : 316; }
  unsigned keysStart() const { return portrait ? 254 : 404; }
  unsigned column(unsigned x, unsigned count) const { return x * count / width(); }
  unsigned boundary(unsigned index, unsigned count) const {
    return (index * width() + count - 1) / count;
  }
};
