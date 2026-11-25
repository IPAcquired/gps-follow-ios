#pragma once
#include <TFT_eSPI.h>
#include "WiredDesktopProtocol.h"
#include "Storage.h"

class WiredDesktop {
 public:
  bool active() const { return open_; }
  void begin(TFT_eSPI& lcd) {
    open_ = true; live_ = false; waitLift_ = true; localBar_ = false;
    touch_.state = 0; ack_ = 0;
    lcd.fillScreen(TFT_BLACK);
    status(lcd);
  }
  void end(TFT_eSPI& lcd) {
    if (!open_) return;
    release();
    // No further clicks are possible after exit; the Pi also releases on link loss.
    alignas(4) uint8_t q[wireddesktop::BufferSize]{}, reply[wireddesktop::BufferSize]{};
    wireddesktop::makeRequest(q, touch_, ack_);
    wiredDesktopExchange(q, reply, wireddesktop::PacketSize);
    lcd.fillScreen(TFT_BLACK);
    open_ = live_ = false;
    closedAt_ = millis();
  }
  // Polls must stop for long enough that the helper discards the prior session.
  bool reopening() const { return closedAt_ && millis() - closedAt_ < 2500; }
  bool poll(TFT_eSPI& lcd, uint16_t threshold) {
    if (reopening()) return true;
    uint32_t now = millis();
    if (live_ && now - lastContent_ >= 3000) {
      release(); clear(lcd); waitLift_ = true;
    }
    uint16_t x = 0, y = 0;
    bool down = lcd.getTouch(&x, &y, threshold);
    if (!down) {
      if (localBar_) { localBar_ = false; return false; }
      waitLift_ = false; release();
    } else if (!waitLift_ && !localBar_) {
      if (y >= wireddesktop::Height) {
        // A drag that enters the bar releases its original remote contact.
        // Only a new press starting over Back can navigate on lift.
        bool remoteDrag = touch_.state == 1;
        release();
        if (!remoteDrag && x < 84) localBar_ = true;
        else waitLift_ = true;
      } else if (live_ && x < wireddesktop::Width &&
                 (touch_.state != 1 || touch_.x != x || touch_.y != y)) {
        touch_.set(1, x, y);
      } else if (!live_) waitLift_ = true;
    }
    alignas(4) uint8_t q[wireddesktop::BufferSize]{}, reply[wireddesktop::BufferSize]{};
    wireddesktop::makeRequest(q, touch_, ack_);
    wireddesktop::Update v;
    if (!wiredDesktopExchange(q, reply, wireddesktop::PacketSize) || !wireddesktop::decode(reply, v))
      return true;
    if (!v.type || v.sequence == ack_) return true;
    ack_ = v.sequence;
    if (v.type == 3) { release(); clear(lcd); waitLift_ = true; }
    else if (v.type == 4) {
      lastContent_ = millis();
      if (!live_) { live_ = true; status(lcd); }
    } else if (live_) {
      lastContent_ = millis();
      if (v.type == 1) lcd.fillRect(v.x, v.y, v.w, v.h, v.color);
      else {
        uint16_t row[28];
        for (unsigned i = 0; i < v.w; ++i) row[i] = wireddesktop::get16(v.pixels + 2*i);
        lcd.setAddrWindow(v.x, v.y, v.w, 1);
        lcd.pushColors(row, v.w, true);
      }
    }
    return true;
  }
 private:
  void release() {
    if (touch_.state == 1) touch_.set(2, touch_.x, touch_.y);
  }
  void status(TFT_eSPI& lcd) {
    lcd.fillRect(0, wireddesktop::Height, 480, 24, TFT_NAVY);
    lcd.setTextColor(TFT_WHITE, TFT_NAVY);
    lcd.drawString("< Back", 8, 300, 2);
    lcd.drawString(live_ ? "Wired desktop" : "Waiting for authorized Pi session", 92, 300, 2);
  }
  void clear(TFT_eSPI& lcd) {
    lcd.fillRect(0, 0, wireddesktop::Width, wireddesktop::Height, TFT_BLACK);
    live_ = false;
    status(lcd);
  }
  bool open_ = false, live_ = false, waitLift_ = true, localBar_ = false;
  uint16_t ack_ = 0;
  uint32_t lastContent_ = 0, closedAt_ = 0;
  wireddesktop::Touch touch_;
};
