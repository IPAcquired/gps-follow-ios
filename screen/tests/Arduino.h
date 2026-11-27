#pragma once
#include <cstddef>
#include <cstdint>
inline uint32_t fakeNow = 10;
inline uint32_t millis() { return fakeNow; }
