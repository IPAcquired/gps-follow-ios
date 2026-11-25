#pragma once
#include <stdint.h>

namespace backdrop {
enum Style : uint8_t { Plain, Grid, Contours, Stars, DriftingStars, SignalSweep, FallingLights, Count };

inline const char* name(uint8_t value) {
  static const char* const names[] = {"Plain", "Grid", "Contours", "Star field", "Drifting stars", "Signal sweep", "Falling lights"};
  return names[value < Count ? value : 0];
}
inline bool animated(uint8_t style) { return style >= DriftingStars && style < Count; }
inline uint16_t tint(uint16_t color, unsigned level) {
  return (((((color >> 11) & 31) * level / 16) << 11) |
          ((((color >> 5) & 63) * level / 16) << 5) | ((color & 31) * level / 16));
}
inline uint16_t base(uint8_t style, uint16_t color) { return style == Plain ? 0 : tint(color, 1); }

// The full motif is drawn only on scene entry. All coordinates stay in the supplied region.
template<class Display>
void motif(Display& lcd, int x, int y, int w, int h, uint8_t style, uint16_t color) {
  if (w <= 0 || h <= 0 || style == Plain || style >= Count) return;
  uint16_t dim = tint(color, 3);
  if (style == Grid || style == SignalSweep) {
    for (int i = 6; i < w; i += 25) lcd.drawFastVLine(x+i, y, h, dim);
    for (int j = 6; j < h; j += 25) lcd.drawFastHLine(x, y+j, w, dim);
  } else if (style == Contours) {
    for (int i = 0; i < w; i += 3) {
      int phase = (i / 2) % 64;
      int offset = phase < 32 ? phase : 63-phase;
      for (int j = offset/2; j < h; j += 25) lcd.drawFastHLine(x+i, y+j, w-i < 3 ? w-i : 3, dim);
    }
  } else {
    unsigned points = 6 + unsigned(w*h)/1450;
    for (unsigned i = 0; i < points; ++i) {
      uint32_t n = (i+1) * 2654435761u;
      int px = int((n >> 15) % unsigned(w)), py = int((n ^ (n >> 7)) % unsigned(h));
      lcd.drawPixel(x+px, y+py, (i%4) ? dim : tint(color, 6));
    }
  }
}

// Only small regions reserved by the layout are animated. Their background is uniform,
// so erasing the previous marks can't damage text, widgets or the static motif.
template<class Display>
void markers(Display& lcd, int x, int y, int w, int h, uint8_t style, uint16_t color, uint32_t phase) {
  if (!animated(style) || w < 2 || h < 2) return;
  unsigned count = w <= 6 ? 3 : 14;
  for (unsigned i = 0; i < count; ++i) {
    uint32_t seed = (i+3) * 2654435761u;
    unsigned col = (seed >> 13) % unsigned(w), row = (seed >> 3) % unsigned(h);
    if (style == SignalSweep) col = (col + phase*(1u+i%2)) % unsigned(w);
    else if (style == FallingLights) row = (row + phase*(1u+i%4)) % unsigned(h);
    else { col = (col + phase) % unsigned(w); row = (row + phase*(1u+i%2)) % unsigned(h); }
    if (style == FallingLights && row+3 < unsigned(h)) lcd.drawFastVLine(x+col,y+row,4,color);
    else if (style == SignalSweep && col+2 < unsigned(w)) lcd.drawFastHLine(x+col,y+row,3,color);
    else lcd.drawPixel(x+col,y+row,color);
  }
}
}
