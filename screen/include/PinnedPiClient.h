#pragma once
#include <WiFiClientSecure.h>
#include "WiredLocalProfile.h"
#include <string.h>

// HTTPClient may reconnect after a peer closes a socket. Every such connection
// must use the same private endpoint and verified DNS identity as the first one.
class PinnedPiClient final : public WiFiClientSecure {
  IPAddress address;
  const char* ca;
  bool handshakeAllowed=false;
 public:
  static const char* hostname(){return localProfileReady()?displayLocalProfile.dns:"";}
  PinnedPiClient(IPAddress target, const char* certificate):address(target),ca(certificate) {}
  // Only the network-loop preflight may allocate a TLS handshake. HTTPClient
  // reconnects during JSON parsing must fail closed and retry next iteration.
  int connectPrepared() {
    if(!localProfileReady())return 0;
    handshakeAllowed=true;
    int result=connect(hostname(),8443,2000);
    handshakeAllowed=false;
    return result;
  }
  int connect(const char* host, uint16_t port) override { return connect(host,port,2000); }
  int connect(const char* host, uint16_t port, int32_t timeout) override {
    if(!handshakeAllowed || !host || strcmp(host,hostname()) || port!=8443 || !ca || !*ca)return 0;
    _timeout=timeout>0&&timeout<=3000?timeout:2000;
    return WiFiClientSecure::connect(address,port,hostname(),ca,nullptr,nullptr);
  }
};
