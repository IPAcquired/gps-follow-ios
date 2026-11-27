#pragma once
#include <stdint.h>
struct TlsMemoryRecovery {
  uint32_t since=0;uint8_t failures=0;
  void success(){failures=0;}
  bool failure(int error,uint32_t now,uint32_t utc,uint32_t previousRestart) {
    // MBEDTLS_ERR_SSL_ALLOC_FAILED. Never treat trust/authentication errors as
    // memory faults, and never downgrade certificate verification.
    if(error!=-0x7F00){failures=0;return false;}
    if(!failures)since=now;
    if(failures<255)++failures;
    if(failures<3||uint32_t(now-since)<5000)return false;
    if(previousRestart&&(utc<previousRestart||utc-previousRestart<300))return false;
    return true;
  }
};
