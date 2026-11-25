#pragma once
#include <stddef.h>
#include <stdint.h>

// A single owner (the UI task) drives one session. No secret enters USB/SPI logs.
class PairChannel {
public:
    bool begin(const uint8_t inner[32]);
    void reset();
    bool established() const;
    bool onRecord(const uint8_t *raw, size_t n, uint8_t out[57], size_t &outLen);
    bool unwrap(const uint8_t *raw, size_t n, uint8_t clear[40], size_t &len);
    bool wrap(const uint8_t *clear, size_t n, uint8_t out[57], size_t &len);
    uint32_t rxCounter() const { return rx_; }
    uint32_t txCounter() const { return tx_; }
private:
    enum class State { Idle, Pending, Open };
    bool enrolled_ = false;
    State state_ = State::Idle;
    uint8_t key_[32]{}, np_[16]{}, ns_[16]{}, session_[80]{}, ready_[22]{};
    uint32_t started_ = 0, tx_ = 0, rx_ = 0;
    bool proof(uint8_t label, uint8_t out[16]) const;
    bool derive();
};
